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
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"strings"

	sofab "github.com/sofa-buffers/corelib-go"

	msg "crucible/driver/go/message"
)

// materialize (oracle/materialized.md), gated by SOFAB_MATERIALIZE=1. Instead of
// the round-trip hex, dump the DECODED value: every field, every array element made
// explicit. The generated struct carries no schema-type tag, so this walker holds
// the schema layout directly (like the C driver's descriptor walk). Floats are raw
// IEEE-754 bit patterns (math.Float32bits/Float64bits), never a decimal rendering.
var materialized = os.Getenv("SOFAB_MATERIALIZE") == "1"

func mF32(x float32) string { return fmt.Sprintf("f%08x", math.Float32bits(x)) }
func mF64(x float64) string { return fmt.Sprintf("F%016x", math.Float64bits(x)) }
func mText(s string) string {
	return fmt.Sprintf("t%d:%s", len(s), hex.EncodeToString([]byte(s)))
}
func mBlob(b []byte) string {
	return fmt.Sprintf("b%d:%s", len(b), hex.EncodeToString(b))
}
func mArr(vals []string) string { return "[" + strings.Join(vals, ",") + "]" }

func materialize(m *msg.Probe) string {
	// top-level scalars (ids 0..7): u8 i8 u16 i16 u32 i32 u64 i64
	f := []string{
		fmt.Sprintf("0:u%d", m.U8),
		fmt.Sprintf("1:s%d", m.I8),
		fmt.Sprintf("2:u%d", m.U16),
		fmt.Sprintf("3:s%d", m.I16),
		fmt.Sprintf("4:u%d", m.U32),
		fmt.Sprintf("5:s%d", m.I32),
		fmt.Sprintf("6:u%d", m.U64),
		fmt.Sprintf("7:s%d", m.I64),
	}

	// nested struct (id 10): f32(0) f64(1) str(2) blob(3)
	n := &m.Nested
	f = append(f, "10:{"+strings.Join([]string{
		"0:" + mF32(n.F32),
		"1:" + mF64(n.F64),
		"2:" + mText(n.Str),
		"3:" + mBlob(n.BytesField),
	}, ";")+"}")

	// arrays struct (id 100): eight numeric arrays (0..7) + nested fp arrays (id 10)
	a := &m.Arrays
	af := make([]string, 0, 9)
	af = append(af, "0:"+mUArr(a.U8), "1:"+mSArr(a.I8), "2:"+mUArr(a.U16),
		"3:"+mSArr(a.I16), "4:"+mUArr(a.U32), "5:"+mSArr(a.I32),
		"6:"+mUArr(a.U64), "7:"+mSArr(a.I64))
	an := &a.Nested
	fp32s := make([]string, 0, arrN)
	for _, x := range an.Fp32 {
		fp32s = append(fp32s, mF32(x))
	}
	fp32s = padArr(fp32s, "f00000000")
	fp64s := make([]string, 0, arrN)
	for _, x := range an.Fp64 {
		fp64s = append(fp64s, mF64(x))
	}
	fp64s = padArr(fp64s, "F0000000000000000")
	af = append(af, "10:{"+strings.Join([]string{
		"0:" + mArr(fp32s), "1:" + mArr(fp64s),
	}, ";")+"}")
	f = append(f, "100:{"+strings.Join(af, ";")+"}")

	// wrapper arrays: string_array (id 200), blob_array (id 201)
	sa := make([]string, len(m.StringArray))
	for i, s := range m.StringArray {
		sa[i] = mText(s)
	}
	f = append(f, "200:"+mArr(sa))
	ba := make([]string, len(m.BlobArray))
	for i, b := range m.BlobArray {
		ba[i] = mBlob(b)
	}
	f = append(f, "201:"+mArr(ba))

	return "{" + strings.Join(f, ";") + "}"
}

// arrN is the schema count for every id-100 numeric/fp array. The oracle
// materializes these to their full N (MESSAGE_SPEC §5.1); the Go corelib only
// fills-to-N when the field is present on the wire, leaving nil when absent, so
// the dump pads to N here to match the reference for absent (default) arrays.
const arrN = 5

func padArr(out []string, def string) []string {
	for len(out) < arrN {
		out = append(out, def)
	}
	return out
}

// mUArr / mSArr materialize a fixed-count numeric array as u/s elements, filled to N.
func mUArr[T uint8 | uint16 | uint32 | uint64](v []T) string {
	out := make([]string, 0, arrN)
	for _, x := range v {
		out = append(out, fmt.Sprintf("u%d", x))
	}
	return mArr(padArr(out, "u0"))
}

func mSArr[T int8 | int16 | int32 | int64](v []T) string {
	out := make([]string, 0, arrN)
	for _, x := range v {
		out = append(out, fmt.Sprintf("s%d", x))
	}
	return mArr(padArr(out, "s0"))
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
