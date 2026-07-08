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
	"os"

	msg "crucible/driver/go/message"
)

// canonical writes the canonical line for one candidate input
// (oracle/canonical.md: decode -> re-encode -> hex).
func canonical(w *bufio.Writer, data []byte) {
	m, err := msg.DecodeProbe(data)
	if err != nil {
		// Coarse reject class (class comparison is soft; see oracle/policy.yaml).
		fmt.Fprint(w, "R invalid_msg\n")
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
