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
	"errors"
	"testing"

	sofab "github.com/sofa-buffers/corelib-go"
	msg "crucible/driver/go/message"
)

func FuzzProbe(f *testing.F) {
	f.Add([]byte{})
	f.Add([]byte{0x00, 0x2a}) // u=42
	f.Fuzz(func(t *testing.T, data []byte) {
		_, _ = msg.DecodeProbe(data) // must not panic on any input
	})
}

// FuzzProbeStream steers on the STREAMING (feed/finish) decode path instead of
// the block-path FuzzProbe above (crucible#178). Nothing else fuzzes it: every
// coverage engine calls the one-shot decode, so feed/finish is only ever
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
// disagree: on the verdict class (A / I / R <class>), or, when both accept, on
// the re-encoded bytes. That is the same intra-driver invariant
// scripts/run-chunked.sh checks over the replay driver (CONTRACT.md: "an
// intra-driver invariant"); this is its fuzz-time form.
func FuzzProbeStream(f *testing.F) {
	f.Add([]byte{0x00, 0x2a}, uint8(1), uint16(1))
	f.Fuzz(func(t *testing.T, data []byte, mode uint8, param uint16) {
		if len(data) == 0 {
			return // CONTRACT rule 4: a length-0 record is not fed at all
		}
		want, wErr := msg.DecodeProbe(data)
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

// decodeProbeChunked mirrors drivers/go/message/probe.go's DecodeProbeFrom, but
// cuts at the fuzz-chosen boundary instead of at a fixed scratch-buffer size,
// and scrubs each fed chunk afterward (0xA5) so a decoder that borrowed from a
// chunk rather than copying out of it is caught here the same way
// SOFAB_CHUNK_SCRUB catches it in the replay driver.
func decodeProbeChunked(data []byte, mode uint8, param int) (*msg.Probe, error) {
	m := msg.NewProbe()
	d := sofab.NewDecoder(m)

	step := len(data)
	twoWay := mode&1 == 0
	if twoWay {
		if param > 0 && param < len(data) {
			step = param
		}
	} else if param > 0 {
		step = param
	}

	var out sofab.Outcome
	var err error
	for off := 0; off < len(data); {
		n := len(data) - off
		if n > step {
			n = step
		}
		if twoWay && off > 0 { // a two-way split is two chunks, not fixed-size
			n = len(data) - off
		}
		chunk := append([]byte(nil), data[off:off+n]...)
		out, err = d.Feed(chunk)
		for i := range chunk {
			chunk[i] = 0xA5
		}
		if err != nil {
			return nil, err
		}
		off += n
	}
	if out != sofab.Complete {
		return nil, sofab.ErrIncomplete
	}
	return m, nil
}

// verdictClass maps a decode error to the verdict class the differential
// comparator would see (oracle/canonical.md): "A", "I" or "R <class>",
// mirroring reject_class in drivers/c/driver.c.
func verdictClass(err error) string {
	switch {
	case err == nil:
		return "A"
	case errors.Is(err, sofab.ErrIncomplete):
		return "I"
	case errors.Is(err, sofab.ErrInvalidMsg):
		return "R invalid_msg"
	case errors.Is(err, sofab.ErrLimitExceeded):
		return "R limit_exceeded"
	case errors.Is(err, sofab.ErrArgument):
		return "R argument"
	case errors.Is(err, sofab.ErrBufferFull):
		return "R buffer_full"
	default:
		return "R other"
	}
}
