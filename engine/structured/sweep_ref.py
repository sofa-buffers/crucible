#!/usr/bin/env python3
"""$ref sweep (crucible#212) over schema/probe-ref.sofab.yaml and its inline twin.

schema/probe-ref.sofab.yaml uses every `$ref` form sofabgen accepts in one message;
schema/probe-ref-inline.sofab.yaml is the same message with every `$ref` written out. The two
are one wire format, so this axis runs against BOTH builds and every vector must get the same
answer from both (scripts/run-ref.sh compares them driver by driver).

What sharing a type can get wrong is a property that belongs to the SITE, not to the shared
type. Each one below is used at two or more sites with different values, so a backend that
keys it on the shared type gets one site wrong, and the inline twin, which has one type per
site, cannot:

  * a union's default_id   Shape at u0 (0), u1 (1), un (omitted = 0), us elements (2), us2
                           elements (0); Tiny at opt.m (0), rec.u / ta / hu / Mixed.t (1); Mixed at
                           mx0 (omitted = 0) and mx1 (1). The generator splits a $defs union into one
                           type per effective default_id; a held option other than default_id is
                           written even at its own default, default_id at its default is omitted.
  * an enum's default      Hue at c0 (0), c2 (2), rec.c (1), opt.c and Mixed.c (2), wc (1).
  * an array's count       every element def at two sites with two counts: Vec2 pts (3) / grid
                           (2 x 2), Hue cs (4) / cs2 (2), Mode fs (2) / fs2 (3), Shape us (2) /
                           us2 (3); and cd's declared default [1, 2].

A string's maxlen belongs to the def, not the site, and is checked at every site of it
(Shape.name 4 at four sites, Far.s 3, Pair.s 2).

and the forms that carry no site property but must still decode alike: a struct def at many
sites (a, b, al alias, pts, grid, opt.p), a def chain (chain), a def holding $ref'd members of
every category (rec), a def holding an inline struct (crate), whole-field copies of a scalar
(level, power), of a union field (hu) and of a union option (wc), a union alias def (ta), a
$defs union built from $refs (mx0, mx1), a cross-file chain over three files (far, deep), a
union from another file (xu), and the payload itself, which is a $ref.

Every vector states its expectation (engine/structured/sweep_run.py checks it):
  ``identity``   the vector IS the canonical form: accepted, re-encodes to its own bytes.
  ``same:<x>``   a non-canonical spelling (an explicit default) that must re-encode to <x>.
  ``reject``     a schema bound is exceeded: every driver must say INVALID.
  ``not_reject`` a prefix of a valid message: complete or incomplete, never INVALID.

Usage: python3 engine/structured/sweep_ref.py [out_dir]   (default corpus/ref)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, hdr, scalar_u, scalar_s, fstr, arr_u, arr_s  # noqa: E402

END = bytes([WT_SEQ_END])


def seq(fid, body=b""):
    """A sequence frame: a struct, a union, a union option, a wrapper array or one of its elements."""
    return hdr(fid, WT_SEQ_BEG) + body + END


# --- the message: field ids of the Body struct (schema/probe-ref.sofab.yaml) -------------
def TAG(v=5):      return scalar_u(0, v)
def A(b=b""):      return seq(1, b)            # Vec2
def B(b=b""):      return seq(2, b)            # Vec2, second site
def C0(v):         return scalar_s(3, v)       # Hue, default 0
def C2(v):         return scalar_s(4, v)       # Hue, default 2
def F(v):          return scalar_u(5, v)       # Mode, default 2 (w), width u8
def U0(b=b""):     return seq(6, b)            # Shape, default_id 0
def U1(b=b""):     return seq(7, b)            # Shape, default_id 1
def UN(b=b""):     return seq(8, b)            # Shape, default_id omitted (= 0)
def PTS(b=b""):    return seq(9, b)            # Vec2[3]
def CS(xs):        return arr_s(10, xs)        # Hue[4], compact
def FS(xs):        return arr_u(11, xs)        # Mode[2], compact
def US(b=b""):     return seq(12, b)           # Shape[2], default_id 2
def GRID(b=b""):   return seq(13, b)           # Vec2[2][2]
def CHAIN(b=b""):  return seq(14, b)           # Outer -> Middle -> Inner
def AL(b=b""):     return seq(15, b)           # Vec2Alias
def OPT(b=b""):    return seq(16, b)           # inline union, default_id 1 (c, default 2)
def REC(b=b""):    return seq(17, b)           # Record
def CRATE(b=b""):  return seq(18, b)           # Crate (inline inner struct)
def LEVEL(v):      return scalar_u(19, v)      # whole-field copy, u8 default 4
def POWER(v):      return scalar_u(20, v)      # whole-field copy, boolean default true
def FAR(b=b""):    return seq(21, b)           # Far, from probe-ref.defs.yaml (Near, Deep inside)
def CS2(xs):       return arr_s(22, xs)        # Hue[2], compact (cs: Hue[4])
def FS2(xs):       return arr_u(23, xs)        # Mode[3], compact (fs: Mode[2])
def US2(b=b""):    return seq(24, b)           # Shape[3], default_id 0 (us: Shape[2], default_id 2)
def MX0(b=b""):    return seq(25, b)           # Mixed, default_id omitted = 0 (p: Vec2)
def MX1(b=b""):    return seq(26, b)           # Mixed, default_id 1 (c: Hue, default 2)
def TA(b=b""):     return seq(27, b)           # TinyAlias, default_id 1 (b = 4)
def HU(b=b""):     return seq(28, b)           # whole-field copy of Holder.u: Tiny, default_id 1
def WC(v):         return scalar_s(29, v)      # whole-field copy of WithC.c: Hue, default 1
def CD(xs):        return arr_s(30, xs)        # Hue[4], declared default [1, 2]
def DEEP(b=b""):   return seq(31, b)           # Deep, from probe-ref-deep.defs.yaml
def XU(b=b""):     return seq(32, b)           # Pair, from probe-ref.defs.yaml, default_id 1 (s)

# Vec2 { x i32 = 7, y i32 }
def x(v): return scalar_s(0, v)
def y(v): return scalar_s(1, v)
# Shape options { num u16 = 5, name string maxlen 4, pt { x i32 = 7 } }
def num(v):     return scalar_u(0, v)
def name(s):    return fstr(1, s)
def pt(b=b""):  return seq(2, b)
# Tiny options { a u8, b u32 = 4 }
def ta(v): return scalar_u(0, v)
def tb(v): return scalar_u(1, v)


def emit_ref(out_dir=None):
    """[(filename, bytes, expect)]; also writes the .bin files when out_dir is given."""
    V = []

    def add(n, data, expect):
        V.append((n + ".bin", data, expect))
        return n + ".bin"

    def canon(n, data):
        return "same:" + add(n, data, "identity")

    def twin(n, data, ref):
        add(n, data, ref)

    omit = canon("a_omit_ctl", TAG())      # every other field at its default

    # ---- A. one struct def at many sites (Vec2: x = 7, y = 0) ---------------------------
    for site, S in (("a", A), ("b", B), ("al_alias", AL)):
        twin(f"a_{site}_x7_explicit_is_default", TAG() + S(x(7)), omit)
        twin(f"a_{site}_empty_frame_is_default", TAG() + S(), omit)
        canon(f"a_{site}_x0_not_default", TAG() + S(x(0)))
        canon(f"a_{site}_y3", TAG() + S(y(3)))
    canon("a_a_and_b_differ", TAG() + A(x(1)) + B(y(2)))

    # ---- B. one enum def at many sites with three defaults -----------------------------
    twin("b_c0_zero_is_default", TAG() + C0(0), omit)
    canon("b_c0_two_written", TAG() + C0(2))
    twin("b_c2_two_is_default", TAG() + C2(2), omit)          # a shared default of 0 writes this
    canon("b_c2_zero_written", TAG() + C2(0))                 # ... and omits this
    canon("b_c2_one_written", TAG() + C2(1))
    canon("b_c0_and_c2_both_one", TAG() + C0(1) + C2(1))
    canon("b_c0_127_inside_the_width", TAG() + C0(127))       # bounded by width, not a closed set
    add("b_c2_128_over_the_width", TAG() + C2(128), "reject")
    twin("b_rec_c_one_is_default", TAG() + REC(scalar_s(0, 1)), omit)
    canon("b_rec_c_zero_written", TAG() + REC(scalar_s(0, 0)))
    canon("b_rec_c_two_written", TAG() + REC(scalar_s(0, 2)))
    # opt: default_id is option c (default 2): c at 2 is the union's default and is omitted
    twin("b_opt_c_two_is_default", TAG() + OPT(scalar_s(1, 2)), omit)
    canon("b_opt_c_zero_written", TAG() + OPT(scalar_s(1, 0)))
    canon("b_opt_c_one_written", TAG() + OPT(scalar_s(1, 1)))

    # ---- C. one bitfield def at four sites (Mode: w set = 2, width u8) ------------------
    twin("c_f_two_is_default", TAG() + F(2), omit)
    canon("c_f_zero_written", TAG() + F(0))
    canon("c_f_seven", TAG() + F(7))
    canon("c_f_255_undeclared_bits_kept", TAG() + F(255))     # the bound is the width; nothing masked
    add("c_f_256_over_the_width", TAG() + F(256), "reject")
    twin("c_rec_f_two_is_default", TAG() + REC(scalar_u(1, 2)), omit)
    canon("c_rec_f_zero_written", TAG() + REC(scalar_u(1, 0)))
    canon("c_opt_f_held_at_its_default_written", TAG() + OPT(scalar_u(2, 2)))   # not default_id
    canon("c_opt_f_zero", TAG() + OPT(scalar_u(2, 0)))
    add("c_opt_f_256_over_the_width", TAG() + OPT(scalar_u(2, 256)), "reject")

    # ---- D. one union def at sites with different default_ids (Shape) ------------------
    # u0: default_id 0 (num = 5) — num 5 is the union's default, omitted; everything else held
    twin("d_u0_num5_is_default", TAG() + U0(num(5)), omit)
    twin("d_u0_empty_frame_is_default", TAG() + U0(), omit)
    canon("d_u0_num0_written", TAG() + U0(num(0)))
    canon("d_u0_name_empty_held_written", TAG() + U0(name("")))
    canon("d_u0_pt_held_empty", TAG() + U0(pt()))
    canon("d_u0_name_abcd", TAG() + U0(name("abcd")))
    add("d_u0_name_over_maxlen", TAG() + U0(name("abcde")), "reject")
    # u1: default_id 1 (name = "") — the mirror image: name "" omitted, num 5 written
    twin("d_u1_name_empty_is_default", TAG() + U1(name("")), omit)
    twin("d_u1_empty_frame_is_default", TAG() + U1(), omit)
    canon("d_u1_num5_held_written", TAG() + U1(num(5)))       # a shared u0 type omits this
    canon("d_u1_num0_written", TAG() + U1(num(0)))
    canon("d_u1_pt_held_empty", TAG() + U1(pt()))
    add("d_u1_name_over_maxlen", TAG() + U1(name("abcde")), "reject")
    # un: default_id omitted = the lowest id (num), so it behaves like u0
    twin("d_un_num5_is_default", TAG() + UN(num(5)), omit)
    canon("d_un_name_empty_held_written", TAG() + UN(name("")))
    canon("d_un_num0_written", TAG() + UN(num(0)))
    # the struct option's member default (x = 7) is the def's, the same at every site
    p_u0 = "same:d_u0_pt_held_empty.bin"
    twin("d_u0_pt_x7_explicit_is_default", TAG() + U0(pt(scalar_s(0, 7))), p_u0)
    canon("d_u0_pt_x0", TAG() + U0(pt(scalar_s(0, 0))))
    canon("d_all_three_sites", TAG() + U0(name("a")) + U1(num(5)) + UN(pt()))
    # switching inside a split type starts the new option at its OWN default
    twin("d_u1_num_then_pt_starts_at_default", TAG() + U1(num(3) + pt()), "same:d_u1_pt_held_empty.bin")
    twin("d_u0_pt_then_num5_is_default", TAG() + U0(pt(scalar_s(0, 1)) + num(5)), omit)

    # ---- E. a split union at an array element (us: Shape, default_id 2 = pt {x = 7}) ----
    def el(i, b=b""): return seq(i, b)
    last = canon("e_us_last_element_at_default_is_framed", TAG() + US(el(0)))
    twin("e_us_pt_x7_explicit_is_default", TAG() + US(el(0, pt(scalar_s(0, 7)))), last)
    twin("e_us_pt_empty_explicit_is_default", TAG() + US(el(0, pt())), last)
    canon("e_us_num5_held_written", TAG() + US(el(0, num(5))))  # default_id 0 elsewhere: omitted there
    canon("e_us_name_empty_held_written", TAG() + US(el(0, name(""))))
    canon("e_us_pt_x1", TAG() + US(el(0, pt(scalar_s(0, 1)))))
    gap = canon("e_us_interior_gap", TAG() + US(el(1, num(3))))
    twin("e_us_interior_default_element_is_a_gap", TAG() + US(el(0) + el(1, num(3))), gap)
    twin("e_us_interior_pt_default_is_a_gap", TAG() + US(el(0, pt()) + el(1, num(3))), gap)
    add("e_us_over_count", TAG() + US(el(2, num(1))), "reject")
    add("e_us_name_over_maxlen", TAG() + US(el(0, name("abcde"))), "reject")

    # ---- F. Tiny at two sites: opt.m (default_id 0) and rec.u (default_id 1, b = 4) -----
    canon("f_opt_m_held_at_its_default_is_a_frame", TAG() + OPT(seq(3)))   # opt's default_id is c
    canon("f_opt_m_b4_written", TAG() + OPT(seq(3, tb(4))))                # b is not m's default_id
    twin("f_opt_m_a0_explicit", TAG() + OPT(seq(3, ta(0))), "same:f_opt_m_held_at_its_default_is_a_frame.bin")
    twin("f_rec_u_b4_is_default", TAG() + REC(seq(2, tb(4))), omit)        # ... but is rec.u's
    canon("f_rec_u_a0_written", TAG() + REC(seq(2, ta(0))))
    canon("f_rec_u_b0_written", TAG() + REC(seq(2, tb(0))))
    canon("f_both_sites", TAG() + OPT(seq(3, tb(4))) + REC(seq(2, ta(0))))

    # ---- G. arrays of a shared element type, each with its own count -------------------
    twin("g_pts_empty_is_default", TAG() + PTS(), omit)
    pd = canon("g_pts_last_element_at_default_is_framed", TAG() + PTS(el(0)))
    twin("g_pts_x7_explicit_is_default", TAG() + PTS(el(0, x(7))), pd)
    canon("g_pts_x1", TAG() + PTS(el(0, x(1))))
    pg = canon("g_pts_interior_gap", TAG() + PTS(el(0, x(1)) + el(2, y(2))))
    twin("g_pts_interior_default_is_a_gap", TAG() + PTS(el(0, x(1)) + el(1) + el(2, y(2))), pg)
    canon("g_pts_three_elements", TAG() + PTS(el(0, x(1)) + el(1, y(1)) + el(2, x(0))))
    add("g_pts_over_count", TAG() + PTS(el(3, x(1))), "reject")             # count 3: index 3 is out
    canon("g_cs_2_0_1", TAG() + CS([2, 0, 1]))
    canon("g_cs_four", TAG() + CS([1, 2, 0, 1]))
    canon("g_cs_127_inside_the_width", TAG() + CS([127]))
    add("g_cs_over_count", TAG() + CS([1, 1, 1, 1, 1]), "reject")          # count 4
    add("g_cs_128_over_the_width", TAG() + CS([128]), "reject")
    canon("g_fs_0_5", TAG() + FS([0, 5]))
    canon("g_fs_255", TAG() + FS([255]))
    add("g_fs_over_count", TAG() + FS([1, 1, 1]), "reject")                # count 2 (pts has 3)
    add("g_fs_256_over_the_width", TAG() + FS([256]), "reject")
    # grid: Vec2[2][2] — the last-element rule at both levels, the count at both levels
    def row(r, *cells): return seq(r, b"".join(cells))
    twin("g_grid_empty_is_default", TAG() + GRID(), omit)
    gd = canon("g_grid_cell_at_default_is_framed", TAG() + GRID(row(0, el(0))))
    twin("g_grid_cell_x7_explicit_is_default", TAG() + GRID(row(0, el(0, x(7)))), gd)
    canon("g_grid_cell_y1", TAG() + GRID(row(0, el(0, y(1)))))
    canon("g_grid_two_rows", TAG() + GRID(row(0, el(1, x(1))) + row(1, el(0, y(2)))))
    add("g_grid_row_over_count", TAG() + GRID(row(2, el(0, x(1)))), "reject")
    add("g_grid_cell_over_count", TAG() + GRID(row(0, el(2, x(1)))), "reject")

    # ---- H. the def chain (Outer -> Middle -> Inner {v = 3}) ----------------------------
    twin("h_chain_v3_explicit_is_default", TAG() + CHAIN(seq(0, seq(0, scalar_u(0, 3)))), omit)
    twin("h_chain_empty_frames_are_default", TAG() + CHAIN(seq(0, seq(0))), omit)
    canon("h_chain_v0", TAG() + CHAIN(seq(0, seq(0, scalar_u(0, 0)))))
    canon("h_chain_n1", TAG() + CHAIN(scalar_u(1, 1)))
    canon("h_chain_v9_n2", TAG() + CHAIN(seq(0, seq(0, scalar_u(0, 9))) + scalar_u(1, 2)))

    # ---- I. a def holding an inline struct; whole-field copies; a def from another file -
    canon("i_crate_inner_z1", TAG() + CRATE(seq(0, scalar_u(0, 1))))
    canon("i_crate_w2", TAG() + CRATE(scalar_u(1, 2)))
    twin("i_crate_inner_z0_is_default", TAG() + CRATE(seq(0, scalar_u(0, 0))), omit)
    twin("i_level_four_is_default", TAG() + LEVEL(4), omit)
    canon("i_level_zero_written", TAG() + LEVEL(0))
    add("i_level_256_over_u8", TAG() + LEVEL(256), "reject")
    twin("i_power_true_is_default", TAG() + POWER(1), omit)
    canon("i_power_false_written", TAG() + POWER(0))
    twin("i_far_q_minus3_is_default", TAG() + FAR(scalar_s(0, -3)), omit)
    canon("i_far_q0", TAG() + FAR(scalar_s(0, 0)))
    canon("i_far_s_abc", TAG() + FAR(fstr(1, "abc")))
    add("i_far_s_over_maxlen", TAG() + FAR(fstr(1, "abcd")), "reject")    # maxlen 3 (Shape.name: 4)

    # ---- J. Vec2 as a union option (opt.p): not opt's default_id, so held it is written ----
    op = canon("j_opt_p_held_at_its_default_is_a_frame", TAG() + OPT(seq(0)))
    twin("j_opt_p_x7_explicit", TAG() + OPT(seq(0, x(7))), op)
    canon("j_opt_p_x0", TAG() + OPT(seq(0, x(0))))
    canon("j_opt_p_y5", TAG() + OPT(seq(0, y(5))))

    # ---- K. the second array site of each element def: another count -------------------
    canon("k_cs_three_fits_count_4", TAG() + CS([1, 1, 1]))
    canon("k_cs2_1_2", TAG() + CS2([1, 2]))
    add("k_cs2_three_over_count_2", TAG() + CS2([1, 1, 1]), "reject")       # cs takes three
    add("k_cs2_128_over_the_width", TAG() + CS2([128]), "reject")
    canon("k_fs2_three_fits_count_3", TAG() + FS2([0, 5, 7]))               # fs rejects three
    add("k_fs2_four_over_count_3", TAG() + FS2([1, 1, 1, 1]), "reject")
    u2 = canon("k_us2_last_element_at_default_is_framed", TAG() + US2(el(0)))
    twin("k_us2_num5_explicit_is_default", TAG() + US2(el(0, num(5))), u2)  # us writes num 5
    canon("k_us2_pt_held_written", TAG() + US2(el(0, pt())))                # us omits pt()
    canon("k_us2_third_element", TAG() + US2(el(2, name("a"))))             # us: index 2 is out
    add("k_us2_over_count_3", TAG() + US2(el(3, num(1))), "reject")

    # ---- L. a $defs union built from $refs, split (mx0: p = Vec2; mx1: c = Hue, default 2) -
    twin("l_mx0_p_empty_is_default", TAG() + MX0(seq(0)), omit)
    twin("l_mx0_p_x7_is_default", TAG() + MX0(seq(0, x(7))), omit)
    canon("l_mx0_p_x1", TAG() + MX0(seq(0, x(1))))
    canon("l_mx0_c_held_at_its_default", TAG() + MX0(scalar_s(1, 2)))       # mx1 omits this
    canon("l_mx0_t_held_empty", TAG() + MX0(seq(2)))
    twin("l_mx1_c2_is_default", TAG() + MX1(scalar_s(1, 2)), omit)
    canon("l_mx1_c0", TAG() + MX1(scalar_s(1, 0)))
    canon("l_mx1_p_held_empty", TAG() + MX1(seq(0)))                        # mx0 omits this
    mt = canon("l_mx1_t_held_at_its_default", TAG() + MX1(seq(2)))
    twin("l_mx1_t_b4_explicit_is_t_default", TAG() + MX1(seq(2, tb(4))), mt)   # Tiny's default_id is b here
    canon("l_mx1_t_a0", TAG() + MX1(seq(2, ta(0))))
    add("l_mx1_c_128_over_the_width", TAG() + MX1(scalar_s(1, 128)), "reject")

    # ---- N. a union alias def; whole-field copies of a union field and a union option ----
    twin("n_ta_b4_is_default", TAG() + TA(tb(4)), omit)
    canon("n_ta_a0_written", TAG() + TA(ta(0)))
    canon("n_ta_b0_written", TAG() + TA(tb(0)))
    twin("n_hu_b4_is_default", TAG() + HU(tb(4)), omit)                     # default_id travelled along
    canon("n_hu_a0_written", TAG() + HU(ta(0)))
    twin("n_wc_one_is_default", TAG() + WC(1), omit)                        # the option's default travelled
    canon("n_wc_zero_written", TAG() + WC(0))
    canon("n_wc_two_written", TAG() + WC(2))

    # ---- O. an array with a declared default, element a $ref'd enum (cd: [1, 2]) ----------
    twin("o_cd_explicit_default_is_omitted", TAG() + CD([1, 2]), omit)
    canon("o_cd_empty_is_written", TAG() + CD([]))                          # §3: M = 0, the explicit empty array
    canon("o_cd_2_1", TAG() + CD([2, 1]))
    canon("o_cd_1", TAG() + CD([1]))
    add("o_cd_over_count", TAG() + CD([1, 1, 1, 1, 1]), "reject")

    # ---- P. the cross-file chain and the cross-file union -------------------------------
    canon("p_far_nr_z0", TAG() + FAR(seq(2, scalar_u(0, 0))))               # Near.z default 2
    twin("p_far_nr_z2_is_default", TAG() + FAR(seq(2, scalar_u(0, 2))), omit)
    canon("p_far_dp_d5", TAG() + FAR(seq(3, scalar_u(0, 5))))
    canon("p_deep_d1", TAG() + DEEP(scalar_u(0, 1)))
    twin("p_deep_d0_is_default", TAG() + DEEP(scalar_u(0, 0)), omit)
    twin("p_xu_s_empty_is_default", TAG() + XU(fstr(1, "")), omit)
    canon("p_xu_i0_held_written", TAG() + XU(scalar_u(0, 0)))
    canon("p_xu_s_ab", TAG() + XU(fstr(1, "ab")))
    add("p_xu_s_over_maxlen", TAG() + XU(fstr(1, "abc")), "reject")         # Pair.s maxlen 2

    # ---- M. a composite touching every field, and every prefix of it --------------------
    whole = (TAG(1) + A(x(1)) + B(y(2)) + C0(2) + C2(0) + F(0) + U0(name("ab")) + U1(num(5))
             + UN(pt(scalar_s(0, 1))) + PTS(el(0, x(1)) + el(2, y(2))) + CS([2, 0, 1]) + FS([0, 5])
             + US(el(1, num(3))) + GRID(row(0, el(0, y(1)))) + CHAIN(seq(0, seq(0, scalar_u(0, 9))))
             + AL(y(4)) + OPT(seq(3, tb(4))) + REC(scalar_s(0, 0) + scalar_u(1, 0) + seq(2, ta(0)))
             + CRATE(seq(0, scalar_u(0, 1)) + scalar_u(1, 2)) + LEVEL(0) + POWER(0)
             + FAR(scalar_s(0, 0) + fstr(1, "abc") + seq(2, scalar_u(0, 0)) + seq(3, scalar_u(0, 5)))
             + CS2([1, 2]) + FS2([0, 5, 7]) + US2(el(2, name("a"))) + MX0(seq(2)) + MX1(seq(0))
             + TA(ta(0)) + HU(ta(0)) + WC(0) + CD([2, 1]) + DEEP(scalar_u(0, 1)) + XU(fstr(1, "ab")))
    canon("m_composite", whole)
    for cut in range(1, len(whole)):
        add(f"m_composite_prefix_{cut:03d}", whole[:cut], "not_reject")

    if out_dir is not None:
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):
            if f.endswith(".bin"):
                os.remove(os.path.join(out_dir, f))
        for n, data, _ in V:
            with open(os.path.join(out_dir, n), "wb") as fh:
                fh.write(data)
    return V


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/ref"
    v = emit_ref(out)
    by = {}
    for _, _, e in v:
        k = "same" if e.startswith("same:") else e
        by[k] = by.get(k, 0) + 1
    print(f"[ref] {len(v)} vectors -> {out}: " + ", ".join(f"{k}={n}" for k, n in sorted(by.items())))


if __name__ == "__main__":
    main()
