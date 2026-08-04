# Minimal: corelib-py only, no sofabgen, no generated code.
from sofab import Encoder
acc = bytearray(); enc = None
def sink(chunk):
    acc.extend(chunk)
    enc.buffer_set(bytearray(1))          # hand back a fresh 1-byte buffer
enc = Encoder.over_buffer(bytearray(1), 0, sink)
enc.write_unsigned(0, 1)                  # field id 0, value 1  ->  00 01
enc.flush()
ref = Encoder(); ref.write_unsigned(0, 1)
print(f"  over_buffer(1) = {bytes(acc).hex()}   in-memory = {ref.getvalue().hex()}")
