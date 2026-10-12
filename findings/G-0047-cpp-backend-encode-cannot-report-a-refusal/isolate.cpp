// Isolate: can a caller of the generated C++ API tell an encode REFUSAL
// (generator#656) from the all-default message, which also encodes to 0 bytes?
#include "probe.hpp"
#include <cstdio>
#include <string>

int main()
{
    // (a) the all-default message: a legal value whose wire form is empty
    message::Probe empty;

    // (b) a value past its schema bound: nested.str is maxlen 32
    message::Probe over;
    over.nested.str = std::string(40, 'x');

    for (auto *p : {&empty, &over})
    {
        const char *what = (p == &empty) ? "all-default" : "over-maxlen ";
        auto v = p->encode();
        std::uint8_t buf[message::Probe::_maxSize];
        std::size_t used = p->encodeTo(buf, sizeof buf);
        sofab::OStreamView os{buf, sizeof buf, 0};
        auto r = p->serialize(os);
        std::printf("%s : encode().size()=%zu  encodeTo()=%zu  serialize().ok()=%d bytesUsed=%zu\n",
                    what, v.size(), used, (int)os.ok(), (size_t)os.bytesUsed());
        (void)r;
    }
    return 0;
}
