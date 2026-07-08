// Native Go coverage engine for the probe decoder.
//
//	go test -fuzz=FuzzProbe ./drivers/go
//
// This exercises the same decode core as the replay driver for coverage-guided
// exploration; it must never panic or hang on any input. Divergence from other
// implementations is caught by the differential comparator, not here.
package main

import (
	"testing"

	msg "crucible/driver/go/message"
)

func FuzzProbe(f *testing.F) {
	f.Add([]byte{})
	f.Add([]byte{0x00, 0x2a}) // u=42
	f.Fuzz(func(t *testing.T, data []byte) {
		_, _ = msg.DecodeProbe(data) // must not panic on any input
	})
}
