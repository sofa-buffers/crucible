// Native Go coverage engine for the probe decoder.
//
//	go test -fuzz=FuzzProbe ./drivers/go
//
// This exercises the same decode core as the replay driver for coverage-guided
// exploration; it must never panic or hang on any input. Divergence from other
// implementations is caught by the differential comparator, not here.
package main

import (
	"bytes"
	"testing"

	msg "crucible/driver/go/message"
)

func FuzzProbe(f *testing.F) {
	f.Add([]byte{})
	f.Add([]byte{0x00, 0x2a}) // u=42
	f.Fuzz(func(t *testing.T, data []byte) {
		_, _ = msg.Probe__Decode(data) // must not panic on any input
	})
}

// FuzzProbeStream steers on the STREAMING (Decoder.Feed) decode path instead of
// the block-path FuzzProbe above (crucible#178). Nothing else fuzzes it: every
// coverage engine calls the one-shot decode, so the chunked path is only ever
// REPLAYED, over a corpus the block path grew.
//
// mode and param are Go's own fuzz arguments (not a header in data, unlike the
// C target's steering engine): mode&1==0 means split = param (mirroring
// SOFAB_SPLIT — two chunks, [0,param) then the rest); mode&1==1 means chunk =
// param (mirroring SOFAB_CHUNK — fixed-size chunks). This is the same pair of
// axes CONTRACT.md's "Decode side" defines for the replay driver, so a
// violation this finds reproduces directly there.
//
// This does not just feed the streaming path and hope a panic turns up --
// every streaming defect found so far (F-0058, F-0060, F-0061, crucible#130)
// was a VALUE or VERDICT mismatch, not a crash, and nothing else would notice
// one here. Each case decodes twice, one-shot and chunked, and fails if they
// disagree: on the verdict class (A / I / L / R <class>), or, when both accept, on
// the re-encoded bytes. That is the same intra-driver invariant
// scripts/run-chunked.sh checks over the replay driver (CONTRACT.md: "an
// intra-driver invariant"); this is its fuzz-time form.
func FuzzProbeStream(f *testing.F) {
	f.Add([]byte{0x00, 0x2a}, uint8(1), uint16(1))
	f.Fuzz(func(t *testing.T, data []byte, mode uint8, param uint16) {
		want, wErr := msg.Probe__Decode(data)
		got, gErr := decodeProbeChunked(data, mode, int(param))

		wantCls, gotCls := verdictClass(wErr), verdictClass(gErr)
		axis, val := "SOFAB_SPLIT", param
		if mode&1 == 1 {
			axis = "SOFAB_CHUNK"
		}
		if wantCls != gotCls {
			t.Fatalf("chunk invariance violation: %s=%d len=%d one-shot=[%s] chunked=[%s]",
				axis, val, len(data), wantCls, gotCls)
		}
		if wantCls != "A" {
			return
		}
		wantEnc, err1 := want.Encode()
		gotEnc, err2 := got.Encode()
		if err1 != nil || err2 != nil || !bytes.Equal(wantEnc, gotEnc) {
			t.Fatalf("chunk invariance violation: %s=%d len=%d re-encode differs "+
				"(one-shot err=%v chunked err=%v)", axis, val, len(data), err1, err2)
		}
	})
}

// decodeProbeChunked maps the fuzz arguments onto the replay driver's own chunked
// decode (decodeChunked in driver.go), with scrubbing always on, so a decoder that
// borrowed from a chunk rather than copying out of it is caught here the same way
// SOFAB_CHUNK_SCRUB catches it in the replay driver.
func decodeProbeChunked(data []byte, mode uint8, param int) (*msg.Probe, error) {
	if mode&1 == 1 {
		return decodeChunked(data, 0, param, true)
	}
	return decodeChunked(data, param, 0, true)
}

// verdictClass maps a decode error to the verdict class the differential
// comparator would see (oracle/canonical.md): "A", or the replay driver's own
// decodeVerdict line — one mapping for both, so they cannot drift apart.
func verdictClass(err error) string {
	if err == nil {
		return "A"
	}
	return decodeVerdict(err)
}
