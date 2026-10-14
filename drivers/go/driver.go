// Crucible Go driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-go code, and
// writes one canonical line per record (oracle/canonical.md) to stdout.
//
// The Go coverage engine is native fuzzing — see fuzz_test.go (FuzzProbe).
package main

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"reflect"
	"strconv"
	"strings"

	sofab "github.com/sofa-buffers/corelib-go"

	msg "crucible/driver/go/message"
)

// materialize (oracle/materialized.md), gated by SOFAB_MATERIALIZE=1. Instead of
// the round-trip hex, dump the DECODED value: every field, every array element made
// explicit. Floats are raw IEEE-754 bit patterns (math.Float32bits/Float64bits),
// never a decimal rendering.
//
// The walk is schema-AGNOSTIC: it holds no hardcoded field layout. The structure —
// field ids, names, kinds, array counts, nesting — is driven entirely by the
// generated descriptor (engine/structured/schema.py → oracle/materialized-schema.json),
// loaded at startup. The generated Go struct is navigated by reflection, resolving
// each descriptor node's schema name against the field's `json:"<schema-name>"` tag.
// Only the per-kind LEAF formatting below is schema-specific.
var materialized = os.Getenv("SOFAB_MATERIALIZE") == "1"

// The streaming-DECODE axis (drivers/common/CONTRACT.md "Decode side"): how the
// bytes of each record reach the decoder. Unset is the one-shot Probe__Decode.
// SOFAB_SPLIT/SOFAB_CHUNK pull: the generated Probe__DecodeFrom reads the record
// through a reader that yields one planned chunk per Read.
// SOFAB_CHUNK_SCRUB pushes: the generated Probe__NewDecoder's Feed on driver-owned
// chunk copies, scrubbed after each call (meta: chunked_decode=push).
var (
	splitAt   = 0     // SOFAB_SPLIT=k: two chunks, [0,k) then [k,end)
	chunkSize = 0     // SOFAB_CHUNK=n: fixed-size chunks of n bytes (wins over split)
	scrub     = false // SOFAB_CHUNK_SCRUB=1: overwrite each fed chunk with 0xA5
)

// The streaming-ENCODE axis (drivers/common/CONTRACT.md "Encode side"): which call
// produces the `A <hex>`. The family is byte-canonical — one value has exactly one
// encoding — so all three surfaces must emit identical bytes, and SOFAB_FLUSH must
// not change them either.
var (
	encSurface = "new" // new | to | stream
	flushSize  = 0     // 0 = unset; only meaningful for `stream`
	failAfter  = 0     // SOFAB_ENCODE_FAIL=n — the destination takes n bytes

	// How often the sink was handed memory that is NOT the installed output buffer.
	// CORELIB_PLAN §5.1.6 forbids that outright — a sink only ever receives bytes
	// inside the installed output buffer, with no pass-through permission to claim —
	// so this is an assertion and not an axis: any count above zero fails the run
	// (see reportForeign). Why the check exists: docs/STATUS-LOG.md (2026-09-14).
	ptForeign = 0
)

// withinBuffer reports whether `inner` is a window into `outer`'s backing array.
// A sink handed anything else received foreign memory, which §5.1.6 forbids.
// (The same test corelib-go's own output_buffer_test.go uses.)
func withinBuffer(outer, inner []byte) bool {
	if len(inner) == 0 {
		return true
	}
	o := outer[:cap(outer)]
	for k := range o {
		if &o[k] == &inner[0] {
			return k+len(inner) <= len(o)
		}
	}
	return false
}

// parseStreamCfg resolves both axes before any record is written, because both
// failures the contract names must land *before* output: an unknown surface, and a
// buffer below this port's declared floor.
func parseStreamCfg() {
	for _, v := range []struct {
		name string
		dst  *int
	}{{"SOFAB_SPLIT", &splitAt}, {"SOFAB_CHUNK", &chunkSize}} {
		if s := os.Getenv(v.name); s != "" {
			n, err := strconv.Atoi(s)
			if err != nil {
				fmt.Fprintf(os.Stderr, "crucible-go: bad %s=%s\n", v.name, s)
				os.Exit(2)
			}
			*v.dst = n
		}
	}
	if s := os.Getenv("SOFAB_CHUNK_SCRUB"); s != "" && s != "0" {
		scrub = true
	}
	if s := os.Getenv("SOFAB_ENCODE"); s != "" {
		switch s {
		case "new", "to", "stream":
			encSurface = s
		default:
			fmt.Fprintf(os.Stderr, "crucible-go: unknown SOFAB_ENCODE=%s "+
				"(this backend has new, to, stream)\n", s)
			os.Exit(2)
		}
	}
	if s := os.Getenv("SOFAB_ENCODE_FAIL"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil || n < 0 {
			fmt.Fprintf(os.Stderr, "crucible-go: bad SOFAB_ENCODE_FAIL=%s\n", s)
			os.Exit(2)
		}
		failAfter = n
	}
	if s := os.Getenv("SOFAB_FLUSH"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil || n < 0 {
			fmt.Fprintf(os.Stderr, "crucible-go: bad SOFAB_FLUSH=%s\n", s)
			os.Exit(2)
		}
		flushSize = n
	}
	// CORELIB_PLAN §5.1: a size at or above the declared MIN_OUTPUT_BUFFER MUST work;
	// one below it MUST be refused where the buffer is handed over — exit 3. Refusing
	// is the *required* answer there, not a failure: it is what stops a port from
	// declaring a high floor to dodge the hard sizes and then quietly accepting them.
	// corelib-go exports the constant (2 x maxVarintLen = 20); drivers/go/meta restates
	// it as min_output_buffer, which is what sizes the gate's sweep.
	if encSurface == "stream" && flushSize > 0 && flushSize < sofab.MinOutputBuffer {
		fmt.Fprintf(os.Stderr, "crucible-go: SOFAB_FLUSH=%d is below this port's "+
			"MIN_OUTPUT_BUFFER=%d — refused at the handover (CORELIB_PLAN §5.1)\n",
			flushSize, sofab.MinOutputBuffer)
		os.Exit(3)
	}
}

// announceCfg prints the resolved configuration on stderr (never parsed). Stdout is
// byte-identical across every chunking and all three surfaces when they are correct,
// so without this a driver that ignored the variables would be indistinguishable from
// one that honours them — which is the vacuous pass the gate's opt-in roster exists to
// prevent.
func announceCfg() {
	if splitAt != 0 || chunkSize != 0 || scrub ||
		encSurface != "new" || flushSize != 0 || failAfter != 0 {
		sc := 0
		if scrub {
			sc = 1
		}
		fmt.Fprintf(os.Stderr, "crucible-go: streaming cfg split=%d chunk=%d scrub=%d "+
			"enc=%s flush=%d fail=%d\n",
			splitAt, chunkSize, sc, encSurface, flushSize, failAfter)
	}
}

// reportForeign states, at clean EOF, how many times the sink received memory that was
// not the installed output buffer. CORELIB_PLAN §5.1.6 forbids that on every flush of
// every message, with no permission flag to set and no exemption to claim, so a count
// above zero is a conformance failure of the corelib and the driver exits non-zero:
// the encode gate already fails a driver that does, which is why this needs no axis of
// its own. The line is printed either way, so a reader can tell the check from a check
// that never ran.
//
// It is a run total rather than per input, because the violation this catches — an
// encoder handing a long string/blob run straight to the sink — only arises on a
// payload larger than the output buffer, which most inputs do not carry.
func reportForeign() {
	if encSurface != "stream" {
		return // no sink installed on this surface: nothing could be handed over
	}
	fmt.Fprintf(os.Stderr, "crucible-go: foreign sink handovers=%d\n", ptForeign)
	if ptForeign > 0 {
		fmt.Fprintf(os.Stderr, "crucible-go: CORELIB_PLAN §5.1.6 — every byte a sink "+
			"receives must lie inside the installed output buffer; %d handover(s) did "+
			"not\n", ptForeign)
		// Point at where the rule and the decision to check it are recorded, so a
		// reader meeting this failure cold need not wonder whether the check is the bug.
		fmt.Fprintf(os.Stderr, "crucible-go: there is no pass-through permission; "+
			"why this is checked: docs/STATUS-LOG.md (2026-09-14). Contract: "+
			"drivers/common/CONTRACT.md\n")
		os.Exit(1)
	}
}

// encodeVia re-encodes through the selected surface. The three are genuinely
// different paths through the corelib, not three names for one call:
//
//	new     -> Encode(): a Probe__MaxSize buffer the generated code allocates, no sink
//	to      -> EncodeTo(w): the caller owns the destination; the corelib drains into
//	           it through a small scratch window of its own
//	stream  -> Serialize() into an encoder this driver builds, with the SOFAB_FLUSH
//	           window, so the encoder crosses a buffer boundary every n bytes
func encodeVia(m *msg.Probe) ([]byte, error) {
	// SOFAB_ENCODE_FAIL=n (CONTRACT.md): hand the encoder a destination of n bytes with
	// NO sink behind it, so a message that does not fit is REFUSED (ErrBufferFull)
	// rather than truncated — CORELIB_PLAN §5.1 forbids returning partial output as if
	// it were complete. It is also the only way the `E` mapping below ever runs: from
	// the wire that branch is unreachable, because every value re-encoded here came out
	// of this driver's own decoder and is in-bounds by construction.
	//
	// The generated EncodeInto is exactly that surface: the caller's buffer, no sink.
	if failAfter > 0 {
		dst := make([]byte, failAfter)
		n, err := m.EncodeInto(dst)
		if err != nil {
			return nil, err
		}
		return dst[:n], nil
	}
	switch encSurface {
	case "to":
		var buf bytes.Buffer
		if err := m.EncodeTo(&buf); err != nil {
			return nil, err
		}
		return buf.Bytes(), nil
	case "stream":
		n := flushSize
		if n == 0 {
			n = msg.Probe__MaxSize
		}
		var acc []byte
		buf := make([]byte, n)
		// The sink COPIES what it is handed (`append`) and never calls SetBuffer, so the
		// buffer it was given stays installed for the whole encode and `withinBuffer`
		// below is a question about one fixed array. Every call is checked: §5.1.6 binds
		// every flush of every message.
		e, err := sofab.NewEncoderSink(buf, 0,
			func(_ *sofab.Encoder, b []byte) error {
				if !withinBuffer(buf, b) {
					ptForeign++
				}
				acc = append(acc, b...)
				return nil
			}, msg.Probe__EncodeOptions()...)
		if err != nil {
			return nil, err
		}
		m.Serialize(e)
		// Flush drains the tail through the sink; the sticky error surfaces here.
		if err := e.Flush(); err != nil {
			return nil, err
		}
		return acc, nil
	default:
		return m.Encode()
	}
}

// schemaNode is one node of the materialized descriptor (oracle/materialized-schema.json).
// A leaf carries only kind; struct carries fields; array/wrapper carry elem + count.
type schemaNode struct {
	ID     int          `json:"id"`
	Name   string       `json:"name"`
	Kind   string       `json:"kind"`
	Elem   string       `json:"elem"`
	Count  int          `json:"count"`
	Fields []schemaNode `json:"fields"`
	// Options is a union's option list (kind "union"), sorted by option id.
	Options []schemaNode `json:"options"`
	// Item is a node_wrapper's nameless element node (a union or another node_wrapper).
	Item *schemaNode `json:"item"`
}

// schemaDoc is the top of the descriptor: { "message": ..., "fields": [node,...] }.
type schemaDoc struct {
	Message string       `json:"message"`
	Fields  []schemaNode `json:"fields"`
}

// schema is the parsed descriptor, populated at startup in materialize mode only.
var schema schemaDoc

// loadSchema reads the descriptor from $SOFAB_MATERIALIZE_SCHEMA (fallback
// oracle/materialized-schema.json) and parses it. Fatal on failure — a materialize
// run with no descriptor cannot produce a correct dump.
func loadSchema() {
	path := os.Getenv("SOFAB_MATERIALIZE_SCHEMA")
	if path == "" {
		path = "oracle/materialized-schema.json"
	}
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintln(os.Stderr, "crucible-go: cannot read materialize schema:", err)
		os.Exit(1)
	}
	if err := json.Unmarshal(data, &schema); err != nil {
		fmt.Fprintln(os.Stderr, "crucible-go: cannot parse materialize schema:", err)
		os.Exit(1)
	}
}

func mF32(x float32) string { return fmt.Sprintf("f%08x", math.Float32bits(x)) }
func mF64(x float64) string { return fmt.Sprintf("F%016x", math.Float64bits(x)) }
func mText(s string) string {
	return fmt.Sprintf("t%d:%s", len(s), hex.EncodeToString([]byte(s)))
}
func mBlob(b []byte) string {
	return fmt.Sprintf("b%d:%s", len(b), hex.EncodeToString(b))
}

// mLeaf formats one scalar value per its schema kind (u|s|fp32|fp64|string|blob),
// pulling the concrete value out of the reflected field. This is the only
// schema-specific formatting left; every leaf and every array element flows here.
func mLeaf(kind string, v reflect.Value) string {
	switch kind {
	case "u":
		return fmt.Sprintf("u%d", v.Uint())
	// §4.4 boolean: rendered as the unsigned value it is on the wire — u1/u0. The
	// generated Go type is a real bool, so only those two are reachable here; a port
	// that kept a non-normalized raw value shows it instead, which is the point.
	case "bool":
		if v.Bool() {
			return "u1"
		}
		return "u0"
	case "s", "enum":
		// enum: the generated type is a named signed integer; print its integer value
		// (a value outside the named members must still come through).
		return fmt.Sprintf("s%d", v.Int())
	case "bitfield":
		return fmt.Sprintf("u%d", v.Uint())
	case "fp32":
		// NOT v.Float(): reflect widens a float32 field to float64, and the
		// fp32 -> fp64 widening SETS the quiet bit, destroying a signaling NaN
		// (CORELIB_PLAN §6.5). Go has a native float32, so take the value out
		// unwidened. This is a Crucible-side hazard, not a corelib one — the
		// generated code and corelib-go keep the value in float32 throughout,
		// which is why the round-trip oracle never saw it (F-0031).
		return mF32(v.Interface().(float32))
	case "fp64":
		return mF64(v.Float())
	case "string":
		return mText(v.String())
	case "blob":
		return mBlob(v.Bytes())
	}
	panic("materialize: unhandled leaf kind " + kind)
}

// fieldByTag returns the struct field of v whose `json` tag equals the schema name.
// The generated struct exports PascalCase names but tags each with its schema name,
// so this is the schema-name → Go-field bridge that keeps the walk schema-agnostic.
func fieldByTag(v reflect.Value, name string) reflect.Value {
	t := v.Type()
	for i := 0; i < t.NumField(); i++ {
		tag := t.Field(i).Tag.Get("json")
		if i := strings.IndexByte(tag, ','); i >= 0 {
			tag = tag[:i]
		}
		if tag == name {
			return v.Field(i)
		}
	}
	panic("materialize: no struct field with json tag " + name)
}

// pascal turns a schema name (as_u16) into the generated Go accessor name (AsU16).
func pascal(name string) string {
	var b strings.Builder
	for _, p := range strings.Split(name, "_") {
		if p != "" {
			b.WriteString(strings.ToUpper(p[:1]) + p[1:])
		}
	}
	return b.String()
}

// walk renders one descriptor node against its reflected value (oracle/materialized.md).
func walk(n *schemaNode, v reflect.Value) string {
	switch n.Kind {
	case "struct":
		parts := make([]string, len(n.Fields))
		for i := range n.Fields {
			c := &n.Fields[i]
			parts[i] = fmt.Sprintf("%d:%s", c.ID, walk(c, fieldByTag(v, c.Name)))
		}
		return "{" + strings.Join(parts, ";") + "}"
	case "union":
		// A union holds exactly one option, so it is walked through the tag —
		// Which() names the held option, its getter yields the value. Testing every
		// option for a non-default value would print `{}` for a held-at-default one.
		if !v.CanAddr() {
			// A getter may hand a nested union back by value; the methods need a pointer.
			p := reflect.New(v.Type())
			p.Elem().Set(v)
			v = p.Elem()
		}
		id := int(v.Addr().MethodByName("Which").Call(nil)[0].Uint())
		for i := range n.Options {
			c := &n.Options[i]
			if c.ID != id {
				continue
			}
			g := v.Addr().MethodByName(pascal(c.Name)).Call(nil)[0]
			if g.Kind() == reflect.Ptr {
				g = g.Elem()
			}
			return fmt.Sprintf("{%d:%s}", c.ID, walk(c, g))
		}
		panic(fmt.Sprintf("materialize: union holds unknown option id %d", id))
	case "array":
		// `count: N` numeric/fp array: emit exactly the elements the container holds.
		// `count` is a CAPACITY, not a length (MESSAGE_SPEC §3): "a decoder
		// materializes exactly the M elements the wire carries … There is no
		// fill-to-N", so padding an absent or short array up to n.Count would invent
		// trailing default elements the wire never carried. n.Count only bounds the
		// field now (M > N is INVALID, §7); it never restores a length.
		out := make([]string, v.Len())
		for i := 0; i < v.Len(); i++ {
			out[i] = mLeaf(n.Elem, v.Index(i))
		}
		return "[" + strings.Join(out, ",") + "]"
	case "wrapper":
		// string_array/blob_array: emit the container's actual elements in index
		// order (its length is itself the signal — no fill-to-N).
		out := make([]string, v.Len())
		for i := range out {
			out[i] = mLeaf(n.Elem, v.Index(i))
		}
		return "[" + strings.Join(out, ",") + "]"
	case "node_wrapper":
		// Dynamic wrapper array of unions / of wrapper arrays: the container's actual
		// elements in index order, each walked through the item node.
		out := make([]string, v.Len())
		for i := range out {
			out[i] = walk(n.Item, v.Index(i))
		}
		return "[" + strings.Join(out, ",") + "]"
	case "struct_wrapper":
		// struct_array (WP-05): a wrapper whose elements are struct sequences —
		// an obj walk per element, container length as-is (like `wrapper`).
		out := make([]string, v.Len())
		for i := range out {
			e := v.Index(i)
			parts := make([]string, len(n.Fields))
			for j := range n.Fields {
				c := &n.Fields[j]
				parts[j] = fmt.Sprintf("%d:%s", c.ID, walk(c, fieldByTag(e, c.Name)))
			}
			out[i] = "{" + strings.Join(parts, ";") + "}"
		}
		return "[" + strings.Join(out, ",") + "]"
	default:
		return mLeaf(n.Kind, v)
	}
}

// materialize walks the whole message: the descriptor's top `fields` list against
// the decoded msg.Probe value (oracle/materialized.md).
func materialize(m *msg.Probe) string {
	v := reflect.ValueOf(m).Elem()
	parts := make([]string, len(schema.Fields))
	for i := range schema.Fields {
		c := &schema.Fields[i]
		parts[i] = fmt.Sprintf("%d:%s", c.ID, walk(c, fieldByTag(v, c.Name)))
	}
	return "{" + strings.Join(parts, ";") + "}"
}

// encodeClass names the canonical class for a refusal of the RE-ENCODE (not of a
// decode): `argument` is §6.3's bad-argument code, which is what a schema-bound
// refusal carries; anything else is a defect of its own and is surfaced as such.
func encodeClass(err error) string {
	switch {
	case errors.Is(err, sofab.ErrArgument):
		return "argument"
	case errors.Is(err, sofab.ErrBufferFull):
		return "buffer_full"
	default:
		return "other"
	}
}

// decodeVerdict maps a non-nil decode error to its canonical line (without the
// newline) by the error's identity. The fuzz target's verdictClass uses it too, so
// the replay driver and the coverage engine cannot classify one error two ways.
//
//	ErrIncomplete     -> I   INCOMPLETE (MESSAGE_SPEC §7): neither accept nor reject;
//	                         no payload (the generated decode returns no partial value)
//	ErrLimitExceeded  -> L   a configured receiver-side cap (generator#102, limit mode
//	                         only): a policy rejection, distinct from INVALID
//	ErrInvalidMsg     -> R invalid_msg
//	ErrArgument       -> R argument      (§6.3's InvalidArgument)
//	ErrBufferFull     -> R buffer_full
//	anything else     -> R other         (e.g. an error generated code raised itself)
func decodeVerdict(err error) string {
	switch {
	case errors.Is(err, sofab.ErrIncomplete):
		return "I"
	case errors.Is(err, sofab.ErrLimitExceeded):
		return "L"
	case errors.Is(err, sofab.ErrInvalidMsg):
		return "R invalid_msg"
	case errors.Is(err, sofab.ErrArgument):
		return "R argument"
	case errors.Is(err, sofab.ErrBufferFull):
		return "R buffer_full"
	default:
		return "R other"
	}
}

// chunkPlan cuts one record into the pieces the decode side feeds
// (drivers/common/CONTRACT.md "Decode side"): chunk>0 → fixed-size chunks of
// `chunk` bytes (last one short); else 0<split<len → [0,split) then [split,len);
// else one chunk holding the whole record. A record of length 0 is ONE empty
// chunk — the decoder answers it, never the driver. The pieces are windows into
// data.
func chunkPlan(data []byte, split, chunk int) [][]byte {
	switch {
	case chunk > 0:
		var out [][]byte
		for off := 0; off < len(data); off += chunk {
			out = append(out, data[off:min(off+chunk, len(data))])
		}
		if len(out) == 0 {
			out = append(out, data)
		}
		return out
	case split > 0 && split < len(data):
		return [][]byte{data[:split], data[split:]}
	default:
		return [][]byte{data}
	}
}

// chunkReader hands a chunk plan to an io.Reader consumer: each Read returns at
// most the rest of the current chunk and never spans two, so the generated
// Probe__DecodeFrom (whose FeedFrom feeds every Read's bytes as one chunk) sees
// exactly the planned boundaries — as long as a chunk fits its 4096-byte scratch
// buffer; a larger chunk is cut further, which only adds boundaries. An empty
// chunk yields nothing, so the empty record reads as an immediate io.EOF.
type chunkReader struct {
	chunks [][]byte
}

func (r *chunkReader) Read(p []byte) (int, error) {
	for len(r.chunks) > 0 && len(r.chunks[0]) == 0 {
		r.chunks = r.chunks[1:]
	}
	if len(r.chunks) == 0 {
		return 0, io.EOF
	}
	n := copy(p, r.chunks[0])
	r.chunks[0] = r.chunks[0][n:]
	return n, nil
}

// decodeChunked decodes one record delivered in pieces (drivers/common/CONTRACT.md
// "Decode side").
//
// Without scrub it PULLS: the generated Probe__DecodeFrom reads the record through
// a chunkReader. Its result is mapped like the one-shot path's: nil → the message,
// sofab.ErrIncomplete → I, anything else → its reject class. FeedFrom feeds each
// Read in order, stops at the first error (terminal), and after EOF answers with
// the decoder's outcome — an Incomplete mid-stream is never terminal there.
//
// With scrub it PUSHES through the generated Probe__NewDecoder, because DecodeFrom
// drains into a scratch buffer of its own that the driver cannot reach: each chunk is
// a copy the driver owns, handed to Feed and overwritten with 0xA5 once Feed returns.
// Feed borrows a chunk only for the call (§6.0), so a decoder that kept a window into
// it would read scrubbed bytes. The verdict is what Feed returns (contract rule 3:
// the decoder has no finish step): a non-nil error is terminal; after the last chunk,
// Complete → the message, Incomplete → sofab.ErrIncomplete, as Probe__DecodeFrom
// reports it.
func decodeChunked(data []byte, split, chunk int, scrub bool) (*msg.Probe, error) {
	plan := chunkPlan(data, split, chunk)
	if !scrub {
		return msg.Probe__DecodeFrom(&chunkReader{chunks: plan})
	}
	d := msg.Probe__NewDecoder()
	var out sofab.Outcome
	for _, c := range plan {
		piece := append([]byte(nil), c...)
		var err error
		out, err = d.Feed(piece)
		for i := range piece {
			piece[i] = 0xA5
		}
		if err != nil {
			return nil, err
		}
	}
	if out != sofab.Complete {
		return nil, sofab.ErrIncomplete
	}
	return d.Message(), nil
}

// canonical writes the canonical line for one candidate input
// (oracle/canonical.md: decode -> re-encode -> hex).
func canonical(w *bufio.Writer, data []byte) {
	var m *msg.Probe
	var err error
	if splitAt != 0 || chunkSize != 0 || scrub {
		m, err = decodeChunked(data, splitAt, chunkSize, scrub)
	} else {
		m, err = msg.Probe__Decode(data)
	}
	if err != nil {
		fmt.Fprintf(w, "%s\n", decodeVerdict(err))
		return
	}
	if materialized {
		// SOFAB_MATERIALIZE=1: dump the decoded value (oracle/materialized.md)
		// instead of the round-trip hex. Only the `A` payload changes.
		fmt.Fprintf(w, "A %s\n", materialize(m))
		return
	}
	b, err := encodeVia(m)
	if err != nil {
		// The re-encode was REFUSED after an accepting decode — its own verdict,
		// never a reject class (oracle/canonical.md "The fifth verdict `E`").
		// Since generator#656 the generated Serialize calls Encoder.RejectArgument
		// for a value past a declared count/maxlen/width, and Encode reports it as
		// sofab.ErrArgument.
		fmt.Fprintf(w, "E %s\n", encodeClass(err))
		return
	}
	fmt.Fprintf(w, "A %s\n", hex.EncodeToString(b))
}

func main() {
	parseStreamCfg()
	announceCfg()
	if materialized {
		loadSchema()
	}

	r := bufio.NewReader(os.Stdin)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()

	var lenbuf [4]byte
	for {
		_, err := io.ReadFull(r, lenbuf[:])
		if err == io.EOF {
			w.Flush()
			reportForeign()
			return // clean EOF at record boundary
		}
		if err != nil {
			fmt.Fprintln(os.Stderr, "crucible-go: short length prefix:", err)
			os.Exit(1)
		}
		n := binary.LittleEndian.Uint32(lenbuf[:])
		data := make([]byte, n)
		if n > 0 {
			if _, err := io.ReadFull(r, data); err != nil {
				fmt.Fprintln(os.Stderr, "crucible-go: short payload:", err)
				os.Exit(1)
			}
		}
		canonical(w, data)
		w.Flush()
	}
}
