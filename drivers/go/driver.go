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
	"fmt"
	"io"
	"math"
	"os"

	msg "crucible/driver/go/message"
)

// canonical writes the canonical line for one candidate input.
func canonical(w *bufio.Writer, data []byte) {
	m, err := msg.DecodeProbe(data)
	if err != nil {
		// Coarse reject class in Phase 1 (class comparison is soft; see
		// oracle/policy.yaml). Refine to the taxonomy in canonical.md later.
		fmt.Fprint(w, "R invalid_msg\n")
		return
	}
	// Accept: fields in ascending schema-id order (u, i, f, s).
	fmt.Fprintf(w, "A u=%d i=%d f=%08x s=%s\n",
		m.U, m.I, math.Float32bits(m.F), hex.EncodeToString([]byte(m.S)))
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
