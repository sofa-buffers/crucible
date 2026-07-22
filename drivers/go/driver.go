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
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"reflect"
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

// schemaNode is one node of the materialized descriptor (oracle/materialized-schema.json).
// A leaf carries only kind; struct carries fields; array/wrapper carry elem + count.
type schemaNode struct {
	ID     int          `json:"id"`
	Name   string       `json:"name"`
	Kind   string       `json:"kind"`
	Elem   string       `json:"elem"`
	Count  int          `json:"count"`
	Fields []schemaNode `json:"fields"`
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
	case "s":
		return fmt.Sprintf("s%d", v.Int())
	case "fp32":
		return mF32(float32(v.Float()))
	case "fp64":
		return mF64(v.Float())
	case "string":
		return mText(v.String())
	case "blob":
		return mBlob(v.Bytes())
	}
	panic("materialize: unhandled leaf kind " + kind)
}

// mDefault is the materialized type default for a numeric/fp array element, used to
// fill-to-N when the Go corelib leaves an absent array nil (short of its schema count).
func mDefault(elem string) string {
	switch elem {
	case "u":
		return "u0"
	case "s":
		return "s0"
	case "fp32":
		return "f00000000"
	case "fp64":
		return "F0000000000000000"
	}
	panic("materialize: unhandled array elem " + elem)
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
	case "array":
		// numeric/fp fixed-count array: emit in-memory elements, then fill-to-N.
		out := make([]string, 0, n.Count)
		for i := 0; i < v.Len(); i++ {
			out = append(out, mLeaf(n.Elem, v.Index(i)))
		}
		for len(out) < n.Count {
			out = append(out, mDefault(n.Elem))
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

// canonical writes the canonical line for one candidate input
// (oracle/canonical.md: decode -> re-encode -> hex).
func canonical(w *bufio.Writer, data []byte) {
	m, err := msg.DecodeProbe(data)
	if err != nil {
		if errors.Is(err, sofab.ErrIncomplete) {
			// INCOMPLETE (MESSAGE_SPEC §7): decode ended mid-message — the third
			// canonical verdict, neither accept nor reject. The corelib returns no
			// partial value here (DecodeProbe drops it), so emit the bare `I`.
			fmt.Fprint(w, "I\n")
			return
		}
		if errors.Is(err, sofab.ErrLimitExceeded) {
			// LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
			// cap on a schema-unbounded field. A policy rejection distinct from INVALID.
			fmt.Fprint(w, "L\n")
			return
		}
		// Coarse reject class (class comparison is soft; see oracle/policy.yaml).
		fmt.Fprint(w, "R invalid_msg\n")
		return
	}
	if materialized {
		// SOFAB_MATERIALIZE=1: dump the decoded value (oracle/materialized.md)
		// instead of the round-trip hex. Only the `A` payload changes.
		fmt.Fprintf(w, "A %s\n", materialize(m))
		return
	}
	b, err := m.Encode()
	if err != nil {
		fmt.Fprint(w, "R other\n")
		return
	}
	fmt.Fprintf(w, "A %s\n", hex.EncodeToString(b))
}

func main() {
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
