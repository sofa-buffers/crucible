#!/usr/bin/env python3
"""Deep union sweep (MESSAGE_SPEC §2, §4.2, §7.4.1) over schema/probe-union-deep.sofab.yaml.

schema/probe-union.sofab.yaml has five LEAF options and one default_id, so it cannot reach
the parts of the union rules that need a struct, array or nested option. This axis does. Every
vector states its expectation, and almost all are one of two kinds:

  * ``identity``  -- the vector IS the canonical form: it must be accepted and re-encode to
                     exactly its own bytes. This is what pins "a held option other than
                     default_id is written even at its own default", because there is no twin
                     for a broken generator to drop the option from as well.
  * ``same:<x>``  -- a non-canonical spelling (several children, a re-opened frame, an option
                     selected and then switched away from and back to) must decode to the value
                     its canonical twin ``<x>`` denotes and re-encode to it.

The canonical forms are derived from the spec, not from any implementation:

  1. A union HOLDS ONE OPTION. The held option is written unless it is default_id at its own
     default; then the whole union is omitted (§2). A held option is written even when it
     equals its own default, as a value, or as a present frame for a struct/union option, or
     in the explicit empty form for an array option.
  2. The last correctly-typed occurrence of any option id is the held option (§7.4.1). A
     different option REPLACES the held one and starts from its own default; the same option
     continues under §7.4 (a scalar and an array are replaced, a struct/union scope merges).
     A mistyped occurrence (§7.3) and an unknown id are not occurrences and never switch.
  3. Inside the held option the ordinary per-field omission rule applies.

What the schema makes observable (schema/probe-union-deep.sofab.yaml, one field per rule):
  choice  non-zero default_id option default, struct option with a non-zero member default,
          empty struct option, compact- and wrapper-array options, enum and fp32 options with
          non-zero defaults
  dflt    default_id is a STRUCT option
  nested  a union whose default_id option is itself a union
  list    an array of unions (last-element rule, interior gaps, re-opened element)
  sparse  non-contiguous option ids, default_id not the lowest
  holder  a union inside a struct
  grid    an array of arrays of unions
  refa/b/c  one $defs union at three sites (default_id 1, 0, omitted)
  chain   union -> struct option -> union -> struct option -> union -> struct option, the
          path MAX_DEPTH is swept through
  choice also carries a bitfield, a blob and a wrapper array of blobs; the `list` element
  carries a blob, a wrapper array of strings and a compact array

Usage: python3 engine/structured/sweep_union_deep.py [out_dir]   (default corpus/union-deep)
       writes the vectors as .bin files, for the differential / chunked / encode passes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (WT_SEQ_BEG, WT_SEQ_END, hdr, scalar_u, scalar_s, fstr, fblob, fp32, fp64,  # noqa: E402
                 arr_u)

END = bytes([WT_SEQ_END])


def seq(fid, body=b""):
    """A sequence frame: the position of a struct, a union, a union option or a wrapper array."""
    return hdr(fid, WT_SEQ_BEG) + body + END


# --- the message: field ids of probe-union-deep.sofab.yaml -------------------------
def TAG(v=5):    return scalar_u(0, v)
def CH(b=b""):   return seq(1, b)          # choice
def DFLT(b=b""): return seq(2, b)          # dflt
def NEST(b=b""): return seq(3, b)          # nested
def LIST(b=b""): return seq(4, b)          # list (wrapper array of unions)
def SPARSE(b=b""): return seq(5, b)        # sparse
def HOLDER(b=b""): return seq(6, b)        # holder
def TRAILER(v):  return scalar_u(7, v)
def GRID(b=b""): return seq(8, b)          # grid (array of arrays of unions)
def REFA(b=b""): return seq(9, b)          # $defs union, default_id 1
def REFB(b=b""): return seq(10, b)         # $defs union, default_id 0
def CHAIN(b=b""): return seq(11, b)        # six declared frames deep
def REFC(b=b""): return seq(12, b)         # $defs union, default_id omitted (= lowest id, 0)

# choice options
def num(v):      return scalar_u(0, v)                 # u16, default 5, = default_id
def pt(b=b""):   return seq(1, b)                      # struct {x i32 =7, y i32}
def ptx(v):      return scalar_s(0, v)
def pty(v):      return scalar_s(1, v)
def stop():      return seq(2)                         # empty struct
def vals(xs):    return arr_u(3, xs)                   # u16[4], compact array
def names(*ss):  return seq(4, b"".join(fstr(i, s) for i, s in enumerate(ss)))
def enm(v):      return scalar_s(5, v)                 # enum {A0,B1,C2}, default 1
def flt(v):      return fp32(6, v)                     # fp32, default 1.5
def flags(v):    return scalar_u(7, v)                 # bitfield {r pos0, w pos1 = true}: default 2, u8
def raw(b):      return fblob(8, b)                    # blob maxlen 4
def blobs(*bs):  return seq(9, b"".join(fblob(i, x) for i, x in enumerate(bs)))  # blob[2], maxlen 4

OMIT = "d_omit_ctl.bin"      # the message whose union fields are all omitted: TAG(5) alone


def emit_union_deep(out_dir=None):
    """[(filename, bytes, expect)]; also writes the .bin files when out_dir is given."""
    V = []

    def add(name, data, expect):
        V.append((name + ".bin", data, expect))
        return name + ".bin"

    def canon(name, data):
        """A vector that is already the canonical form. Returns the `same:` reference to it."""
        return "same:" + add(name, data, "identity")

    def twin(name, data, ref):
        add(name, data, ref)

    omit = canon("d_omit_ctl", TAG())

    # ---- A. default_id with a NON-ZERO option default ------------------------------
    # `num` is default_id 0 with default 5: 5 is the union's default and is omitted, 0 is a
    # different value and is written. A generator that omits "the zero" instead gets 0 wrong.
    twin("a_num5_explicit_omits", TAG() + CH(num(5)), omit)
    canon("a_num0_written", TAG() + CH(num(0)))
    n6 = canon("a_num6", TAG() + CH(num(6)))
    twin("a_empty_frame_omits", TAG() + CH(), omit)
    num3 = canon("a_num3", TAG() + CH(num(3)))

    # ---- B. a STRUCT option with a non-zero member default (x = 7) ------------------
    p_empty = canon("b_pt_held_all_default", TAG() + CH(pt()))        # present, empty frame
    twin("b_pt_x7_explicit_is_default", TAG() + CH(pt(ptx(7))), p_empty)
    canon("b_pt_x0_not_default", TAG() + CH(pt(ptx(0))))              # 0 != 7: written
    canon("b_pt_y5", TAG() + CH(pt(pty(5))))                          # x at default omitted
    p_y = canon("b_pt_y2", TAG() + CH(pt(pty(2))))                    # the "restarted" value below
    p_xy = canon("b_pt_x1_y2", TAG() + CH(pt(ptx(1) + pty(2))))
    twin("b_pt_children_out_of_order", TAG() + CH(pt(pty(2) + ptx(1))), p_xy)
    twin("b_num_then_empty_pt", TAG() + CH(num(3) + pt()), p_empty)   # selecting pt starts at defaults

    # ---- C. the empty struct option: a signal that can only be sent as a frame ------
    stop_c = canon("c_stop_held", TAG() + CH(stop()))
    twin("c_num_then_stop", TAG() + CH(num(3) + stop()), stop_c)
    twin("c_stop_then_num", TAG() + CH(stop() + num(3)), num3)

    # ---- D. §7.4.1 decode: which option is held, and what it starts from ------------
    twin("d_same_struct_option_continues", TAG() + CH(pt(ptx(1)) + pt(pty(2))), p_xy)
    twin("d_same_struct_option_across_frames", TAG() + CH(pt(ptx(1))) + CH(pt(pty(2))), p_xy)
    # away and back: pt is discarded by num and restarts from ITS OWN default (x = 7, not the
    # 1 it held, not 0). Three implementations of "restart" give three different x.
    twin("d_away_and_back_restarts_at_default", TAG() + CH(pt(ptx(1)) + num(3) + pt(pty(2))), p_y)
    twin("d_away_and_back_across_frames",
         TAG() + CH(pt(ptx(1))) + CH(num(3)) + CH(pt(pty(2))), p_y)
    twin("d_default_id_reselected_at_default_omits", TAG() + CH(pt(ptx(1)) + num(5)), omit)
    twin("d_default_id_reselected_at_zero", TAG() + CH(pt(ptx(1)) + num(0)),
         "same:a_num0_written.bin")
    twin("d_scalar_option_repeated", TAG() + CH(num(1) + num(6)), n6)
    twin("d_unknown_id_does_not_switch_or_reset",
         TAG() + CH(pt(ptx(1)) + scalar_u(9, 1) + pt(pty(2))), p_xy)
    twin("d_mistyped_option_does_not_switch_or_reset",
         TAG() + CH(pt(ptx(1)) + scalar_u(1, 4) + pt(pty(2))), p_xy)
    twin("d_mistyped_after_scalar_keeps_it", TAG() + CH(num(3) + scalar_u(1, 4)), num3)
    twin("d_mistyped_alone_holds_nothing", TAG() + CH(scalar_u(1, 4)), omit)
    twin("d_unknown_alone_holds_nothing", TAG() + CH(scalar_u(9, 4)), omit)
    x1 = canon("d_ctl_pt_x1", TAG() + CH(pt(ptx(1))))
    twin("d_unknown_member_inside_option_skipped", TAG() + CH(pt(ptx(1) + scalar_u(9, 1))), x1)
    twin("d_struct_option_selected_then_dropped_by_leaf", TAG() + CH(pt(ptx(1), ) + num(6)), n6)

    # ---- E. ARRAY options -----------------------------------------------------------
    v_empty = canon("e_vals_held_empty", TAG() + CH(vals([])))        # the explicit empty form
    canon("e_vals_1_2", TAG() + CH(vals([1, 2])))
    v9 = canon("e_vals_9", TAG() + CH(vals([9])))
    twin("e_vals_repeated_is_replaced", TAG() + CH(vals([1, 2]) + vals([9])), v9)
    twin("e_vals_away_and_back_is_replaced", TAG() + CH(vals([1, 2]) + num(3) + vals([9])), v9)
    twin("e_vals_then_empty_vals", TAG() + CH(vals([1, 2]) + vals([])), v_empty)
    canon("e_names_held_empty", TAG() + CH(names()))
    canon("e_names_a", TAG() + CH(names("a")))
    canon("e_names_a_b", TAG() + CH(names("a", "b")))
    nb = canon("e_names_gap_b", TAG() + CH(seq(4, fstr(1, "b"))))
    # a wrapper array is REPLACED whole when re-opened (§7.4): "a" is gone, index 0 is a gap
    twin("e_names_reopened_is_replaced",
         TAG() + CH(seq(4, fstr(0, "a")) + seq(4, fstr(1, "b"))), nb)

    # ---- F. non-integer options with NON-ZERO defaults ------------------------------
    canon("f_enum_at_its_default_written", TAG() + CH(enm(1)))       # default 1, not default_id
    canon("f_enum_zero_written", TAG() + CH(enm(0)))
    canon("f_fp32_at_its_default_written", TAG() + CH(flt(1.5)))
    canon("f_fp32_zero_written", TAG() + CH(flt(0.0)))
    f2 = canon("f_ctl_fp32_2", TAG() + CH(flt(2.0)))
    twin("f_enum_then_fp32", TAG() + CH(enm(2) + flt(2.0)), f2)

    # ---- G. default_id is a STRUCT option (dflt: pt {q = 9}) ------------------------
    twin("g_default_frame_omits", TAG() + DFLT(), omit)
    twin("g_default_id_pt_at_default_omits", TAG() + DFLT(seq(1, scalar_u(0, 9))), omit)
    canon("g_pt_q3", TAG() + DFLT(seq(1, scalar_u(0, 3))))
    canon("g_pt_q0_not_default", TAG() + DFLT(seq(1, scalar_u(0, 0))))
    canon("g_a_zero_held_written", TAG() + DFLT(scalar_u(0, 0)))
    twin("g_a_then_empty_pt_is_default", TAG() + DFLT(scalar_u(0, 1) + seq(1)), omit)
    # away and back with a non-zero member default: q must restart at 9 (the default), so the
    # union is at its default again and disappears; q = 3 kept, or q = 0, would not.
    twin("g_away_and_back_restarts_q_at_default",
         TAG() + DFLT(seq(1, scalar_u(0, 3)) + scalar_u(0, 4) + seq(1)), omit)

    # ---- H. union of union -----------------------------------------------------------
    twin("h_default_frame_omits", TAG() + NEST(), omit)
    twin("h_inner_empty_frame_omits", TAG() + NEST(seq(1)), omit)
    twin("h_inner_b_at_default_omits", TAG() + NEST(seq(1, fp64(1, 2.5))), omit)
    canon("h_inner_a_zero_held", TAG() + NEST(seq(1, scalar_s(0, 0))))
    h5 = canon("h_inner_b_3", TAG() + NEST(seq(1, fp64(1, 3.0))))
    h6 = canon("h_flag_false_held", TAG() + NEST(scalar_u(0, 0)))
    canon("h_flag_true", TAG() + NEST(scalar_u(0, 1)))
    ha1 = canon("h_ctl_inner_a1", TAG() + NEST(seq(1, scalar_s(0, 1))))
    twin("h_flag_then_inner", TAG() + NEST(scalar_u(0, 1) + seq(1, scalar_s(0, 1))), ha1)
    twin("h_inner_then_flag_false", TAG() + NEST(seq(1, scalar_s(0, 1)) + scalar_u(0, 0)), h6)
    twin("h_away_and_back_inner_restarts",
         TAG() + NEST(seq(1, scalar_s(0, 1)) + scalar_u(0, 1) + seq(1)), omit)
    twin("h_inner_switches_option_in_reopened_frame",
         TAG() + NEST(seq(1, scalar_s(0, 1)) + seq(1, fp64(1, 3.0))), h5)

    # ---- I. array of unions (count 3, default_id = struct option p {q = 9}) ---------
    def el(i, b=b""): return seq(i, b)        # a list element: a union frame at index i
    def li(x): return scalar_s(0, x)          # option i (i32)
    def ls(s): return fstr(1, s)              # option s (string)
    def lp(q): return seq(2, scalar_u(0, q))  # option p (struct {q})

    twin("i_empty_array_omits", TAG() + LIST(), omit)
    canon("i_elem0_i5", TAG() + LIST(el(0, li(5))))
    canon("i_elem0_i0_held_written", TAG() + LIST(el(0, li(0))))
    last_default = canon("i_last_element_at_default_is_framed", TAG() + LIST(el(0)))
    twin("i_last_element_p_q9_explicit", TAG() + LIST(el(0, lp(9))), last_default)
    canon("i_elem0_p_q3", TAG() + LIST(el(0, lp(3))))
    canon("i_elem0_s_empty_held", TAG() + LIST(el(0, ls(""))))
    i_gap = canon("i_interior_gap", TAG() + LIST(el(0, li(3)) + el(2, li(4))))
    twin("i_interior_default_element_is_a_gap",
         TAG() + LIST(el(0, li(3)) + el(1) + el(2, li(4))), i_gap)
    sx = canon("i_ctl_elem0_s_x", TAG() + LIST(el(0, ls("x"))))
    twin("i_element_two_options_last_wins", TAG() + LIST(el(0, li(5) + ls("x"))), sx)
    twin("i_element_reopened_last_wins", TAG() + LIST(el(0, li(5)) + el(0, ls("x"))), sx)
    i6 = canon("i_ctl_gap_elem1_i6", TAG() + LIST(el(1, li(6))))
    twin("i_wrapper_reopened_is_replaced", TAG() + LIST(el(0, li(5))) + LIST(el(1, li(6))), i6)

    # ---- J. non-contiguous option ids (a = 3, b = 7 = default_id) --------------------
    twin("j_default_id_at_default_omits", TAG() + SPARSE(fstr(7, "")), omit)
    jb = canon("j_b_x", TAG() + SPARSE(fstr(7, "x")))
    canon("j_a_zero_held_written", TAG() + SPARSE(scalar_u(3, 0)))
    ja = canon("j_a_1", TAG() + SPARSE(scalar_u(3, 1)))
    twin("j_gap_id_after_held_is_skipped", TAG() + SPARSE(scalar_u(3, 1) + scalar_u(5, 9)), ja)
    twin("j_gap_id_alone_holds_nothing", TAG() + SPARSE(scalar_u(4, 1)), omit)
    twin("j_id_past_the_last_option", TAG() + SPARSE(scalar_u(8, 1)), omit)
    twin("j_a_then_b", TAG() + SPARSE(scalar_u(3, 1) + fstr(7, "x")), jb)
    twin("j_b_then_a", TAG() + SPARSE(fstr(7, "x") + scalar_u(3, 1)), ja)

    # ---- K. a union inside a struct ---------------------------------------------------
    def hu(b=b""): return seq(0, b)           # holder.u
    twin("k_empty_struct_omits", TAG() + HOLDER(), omit)
    canon("k_b_empty_held_forces_the_struct", TAG() + HOLDER(hu(fstr(1, ""))))
    twin("k_default_id_at_default_omits_struct", TAG() + HOLDER(hu(scalar_u(0, 0))), omit)
    canon("k_a3", TAG() + HOLDER(hu(scalar_u(0, 3))))
    canon("k_n2_only", TAG() + HOLDER(scalar_u(1, 2)))
    k6 = canon("k_ctl_a4_n1", TAG() + HOLDER(hu(scalar_u(0, 4)) + scalar_u(1, 1)))
    twin("k_last_option_wins_inside_struct",
         TAG() + HOLDER(hu(fstr(1, "x") + scalar_u(0, 4)) + scalar_u(1, 1)), k6)
    k7 = canon("k_ctl_a4", TAG() + HOLDER(hu(scalar_u(0, 4))))
    twin("k_struct_and_union_reopened",
         TAG() + HOLDER(hu(fstr(1, "x"))) + HOLDER(hu(scalar_u(0, 4))), k7)

    # ---- N. bitfield, enum width, blob and wrapper-array-of-blob options --------------------
    canon("n_flags_default_written", TAG() + CH(flags(2)))            # bit 1 set = its default, written
    canon("n_flags_zero_written", TAG() + CH(flags(0)))
    canon("n_flags_1", TAG() + CH(flags(1)))
    canon("n_flags_255_undeclared_bits_kept", TAG() + CH(flags(255)))  # the bound is the WIDTH, nothing is masked
    add("n_flags_256_over_the_declared_width", TAG() + CH(flags(256)), "reject")
    twin("n_flags_then_num", TAG() + CH(flags(1) + num(3)), num3)
    canon("n_enum_127_inside_width_outside_the_values", TAG() + CH(enm(127)))  # not a closed set
    canon("n_enum_minus_1", TAG() + CH(enm(-1)))
    add("n_enum_128_over_the_declared_width", TAG() + CH(enm(128)), "reject")
    raw_e = canon("n_raw_empty_held", TAG() + CH(raw(b"")))
    canon("n_raw_abcd", TAG() + CH(raw(b"abcd")))
    add("n_raw_over_maxlen", TAG() + CH(raw(b"abcde")), "reject")
    raw_cd = canon("n_raw_cd", TAG() + CH(raw(b"cd")))
    twin("n_raw_repeated_is_replaced", TAG() + CH(raw(b"ab") + raw(b"cd")), raw_cd)
    twin("n_raw_away_and_back_restarts_empty", TAG() + CH(raw(b"ab") + num(3) + raw(b"")), raw_e)
    bl_e = canon("n_blobs_held_empty", TAG() + CH(blobs()))
    canon("n_blobs_x", TAG() + CH(blobs(b"x")))
    canon("n_blobs_empty_blob_is_the_last_element", TAG() + CH(blobs(b"")))
    bl_gap = canon("n_blobs_gap_y", TAG() + CH(seq(9, fblob(1, b"y"))))
    twin("n_blobs_reopened_is_replaced", TAG() + CH(blobs(b"x") + seq(9, fblob(1, b"y"))), bl_gap)
    twin("n_blobs_away_and_back_restarts_empty", TAG() + CH(blobs(b"x") + num(3) + blobs()), bl_e)
    add("n_blobs_element_over_maxlen", TAG() + CH(blobs(b"abcde")), "reject")

    # ---- O. blob / wrapper-array / compact-array options INSIDE an array-of-unions element ---
    def lr(b):  return fblob(3, b)                 # option r (blob maxlen 4)
    def lws(*ss): return seq(4, b"".join(fstr(i, x) for i, x in enumerate(ss)))   # option ws (string[2])
    def lns(xs):  return arr_u(5, xs)              # option ns (u8[4], compact)
    canon("o_r_empty_held", TAG() + LIST(el(0, lr(b""))))
    canon("o_r_ab", TAG() + LIST(el(0, lr(b"ab"))))
    canon("o_ws_held_empty", TAG() + LIST(el(0, lws())))
    canon("o_ws_a", TAG() + LIST(el(0, lws("a"))))
    canon("o_ns_held_empty", TAG() + LIST(el(0, lns([]))))
    canon("o_ns_1_2", TAG() + LIST(el(0, lns([1, 2]))))
    ns1 = canon("o_ctl_ns_1", TAG() + LIST(el(0, lns([1]))))
    twin("o_r_then_ns_last_wins", TAG() + LIST(el(0, lr(b"ab") + lns([1]))), ns1)
    wsb = canon("o_ctl_ws_gap_b", TAG() + LIST(el(0, seq(4, fstr(1, "b")))))
    twin("o_ws_away_and_back_restarts_empty",
         TAG() + LIST(el(0, lws("a") + li(3) + seq(4, fstr(1, "b")))), wsb)
    add("o_ns_over_count", TAG() + LIST(el(0, lns([1, 2, 3, 4, 5]))), "reject")
    add("o_r_over_maxlen", TAG() + LIST(el(0, lr(b"abcde"))), "reject")

    # ---- P. an array of arrays of unions (grid: count 2 x count 2, default_id 1 = hi = 4) -----
    def cell(c, b=b""): return seq(c, b)          # a union element of a row
    def row(r, *cells): return seq(r, b"".join(cells))
    def lo(v): return scalar_u(0, v)
    def hi(v): return scalar_u(1, v)
    twin("p_empty_grid_omits", TAG() + GRID(), omit)
    canon("p_cell_lo3", TAG() + GRID(row(0, cell(0, lo(3)))))
    canon("p_cell_lo0_held_written", TAG() + GRID(row(0, cell(0, lo(0)))))
    cdef = canon("p_cell_at_default_is_framed", TAG() + GRID(row(0, cell(0))))
    twin("p_cell_hi4_explicit_is_default", TAG() + GRID(row(0, cell(0, hi(4)))), cdef)
    canon("p_two_cells", TAG() + GRID(row(0, cell(0, lo(1)), cell(1, hi(9)))))
    row1 = canon("p_row1_only_row0_is_a_gap", TAG() + GRID(row(1, cell(0, lo(3)))))
    twin("p_empty_interior_row_is_a_gap", TAG() + GRID(seq(0) + row(1, cell(0, lo(3)))), row1)
    g9 = canon("p_gap_cell_hi9", TAG() + GRID(row(0, cell(1, hi(9)))))
    twin("p_row_reopened_is_replaced", TAG() + GRID(row(0, cell(0, lo(1))) + row(0, cell(1, hi(9)))), g9)
    g9b = canon("p_ctl_cell_hi9", TAG() + GRID(row(0, cell(0, hi(9)))))
    twin("p_cell_two_options_last_wins", TAG() + GRID(row(0, cell(0, lo(1) + hi(9)))), g9b)
    g2 = canon("p_ctl_row1_lo2", TAG() + GRID(row(1, cell(0, lo(2)))))
    twin("p_grid_reopened_is_replaced", TAG() + GRID(row(0, cell(0, lo(1)))) + GRID(row(1, cell(0, lo(2)))), g2)

    # ---- P2. a mistyped element past the capacity is skipped (§7.3 wins over the §7 bound) ---
    # G-0045: the C++ backends apply the nested-array bound before the wire-type skip. A skipped
    # element is no element, so the frame stays what it was; a well-typed one at that index is INVALID.
    twin("p_grid_mistyped_overindex_is_skipped", TAG() + GRID(scalar_s(6, 24)), omit)
    twin("p_grid_mistyped_first_overindex_is_skipped", TAG() + GRID(scalar_s(2, 24)), omit)
    twin("p_grid_mistyped_inrange_is_skipped", TAG() + GRID(scalar_s(0, 24)), omit)
    add("p_grid_welltyped_overindex_rejects", TAG() + GRID(seq(2)), "reject")
    twin("p_grid_row_mistyped_overindex_is_skipped", TAG() + GRID(row(0, scalar_s(2, 24))),
         canon("p_ctl_grid_row_held_empty", TAG() + GRID(seq(0))))
    add("p_grid_row_welltyped_overindex_rejects", TAG() + GRID(row(0, cell(2))), "reject")
    twin("p_list_mistyped_overindex_is_skipped", TAG() + LIST(scalar_s(5, 24)), omit)
    add("p_list_welltyped_overindex_rejects", TAG() + LIST(el(5)), "reject")
    twin("p_names_mistyped_overindex_is_skipped", TAG() + CH(seq(4, scalar_u(5, 1))),
         canon("p_ctl_names_held_empty", TAG() + CH(names())))
    add("p_names_welltyped_overindex_rejects", TAG() + CH(names("a", "b", "c")), "reject")

    # ---- Q. one $defs union at three sites: one type per effective default_id ---------------
    # refa: default_id 1 (name, default "")   refb: default_id 0 (num, default 5)
    # refc: default_id omitted = lowest id = 0, so it must behave exactly like refb
    twin("q_refa_default_id_name_empty_omits", TAG() + REFA(fstr(1, "")), omit)
    canon("q_refa_num5_written", TAG() + REFA(scalar_u(0, 5)))         # held, != default_id, at ITS default
    canon("q_refa_num0_written", TAG() + REFA(scalar_u(0, 0)))
    qpt = canon("q_refa_pt_held", TAG() + REFA(seq(2)))
    twin("q_refa_pt_x7_explicit_is_default", TAG() + REFA(seq(2, scalar_s(0, 7))), qpt)
    canon("q_refa_name_x", TAG() + REFA(fstr(1, "x")))
    add("q_refa_name_over_maxlen", TAG() + REFA(fstr(1, "abcde")), "reject")
    twin("q_refb_default_id_num5_omits", TAG() + REFB(scalar_u(0, 5)), omit)
    canon("q_refb_name_empty_written", TAG() + REFB(fstr(1, "")))      # refa omits this, refb must write it
    canon("q_refb_pt_held", TAG() + REFB(seq(2)))
    twin("q_refc_default_id_omitted_means_lowest_num5_omits", TAG() + REFC(scalar_u(0, 5)), omit)
    canon("q_refc_name_empty_written", TAG() + REFC(fstr(1, "")))

    # ---- R. the declared chain, and MAX_DEPTH swept THROUGH it -----------------------------
    canon("r_chain_a_3", TAG() + CHAIN(scalar_u(0, 3)))
    twin("r_chain_a_zero_is_default_id_at_default", TAG() + CHAIN(scalar_u(0, 0)), omit)
    c_s = canon("r_chain_s_held_empty", TAG() + CHAIN(seq(1)))
    twin("r_chain_inner_a_default_leaves_s_empty", TAG() + CHAIN(seq(1, seq(0, scalar_u(0, 0)))), c_s)
    canon("r_chain_middle_s_held", TAG() + CHAIN(seq(1, seq(0, seq(1)))))
    deep_empty = canon("r_chain_innermost_s_held",
                       TAG() + CHAIN(seq(1, seq(0, seq(1, seq(0, seq(1)))))))
    deep_full = canon("r_chain_full_leaf7",
                      TAG() + CHAIN(seq(1, seq(0, seq(1, seq(0, seq(1, scalar_u(0, 7))))))))
    twin("r_chain_leaf_zero_is_default",
         TAG() + CHAIN(seq(1, seq(0, seq(1, seq(0, seq(1, scalar_u(0, 0))))))), deep_empty)
    twin("r_chain_away_and_back_restarts", TAG() + CHAIN(seq(1, seq(0, scalar_u(0, 4)) ) + scalar_u(0, 3) + seq(1)), c_s)
    twin("r_chain_reopened_continues",
         TAG() + CHAIN(seq(1, seq(0, scalar_u(0, 4)))) + CHAIN(seq(1, seq(0, seq(1, seq(0, seq(1, scalar_u(0, 7))))))),
         deep_full)

    # MAX_DEPTH (255) is a WIRE limit, not a schema one: an unknown sequence may nest
    # arbitrarily inside a known one. A declared frame and a skipped subtree use different
    # counters (F-0050; F-0055 was a scope stack sized from the schema). Nest unknown id 50
    # inside the innermost scope of four different declared paths, to exactly 255 (legal)
    # and 256 (INVALID, even when every sequence is closed), closed and truncated.
    def unk(k, closed):
        return hdr(50, WT_SEQ_BEG) * k + (END * k if closed else b"")

    def open_path(frames):
        return b"".join(hdr(f, WT_SEQ_BEG) for f in frames)

    paths = [
        # (name, declared frames, the canonical twin once the skipped subtree is dropped)
        ("chain_innermost", (11, 1, 0, 1, 0, 1), deep_empty),
        ("choice_union_frame", (1,), omit),
        ("choice_struct_option", (1, 1), p_empty),
        ("list_element_struct_option", (4, 0, 2), last_default),
    ]
    for pname, frames, ref in paths:
        d = len(frames)
        for total, closed in ((255, True), (255, False), (256, True), (256, False)):
            body = open_path(frames) + unk(total - d, closed) + (END * d if closed else b"")
            data = TAG() + body
            name = f"s_depth_{total}_{'closed' if closed else 'truncated'}_via_{pname}"
            if total == 255 and closed:
                twin(name, data, ref)                      # accepted, and the skipped nest vanishes
            elif total == 255:
                add(name, data, "not_reject")              # a prefix of a valid message: A or I
            else:
                add(name, data, "reject")                  # 256 opens: INVALID, closed or not

    # ---- L. schema-bound violations inside an option -----------------------------------
    add("l_array_option_over_count", TAG() + CH(vals([1, 2, 3, 4, 5])), "reject")
    add("l_string_option_over_maxlen", TAG() + SPARSE(fstr(7, "abcde")), "reject")

    # ---- M. a composite touching every field, and every prefix of it -------------------
    whole = (TAG(1) + CH(pt(ptx(1) + pty(2))) + DFLT(seq(1, scalar_u(0, 3)))
             + NEST(seq(1, scalar_s(0, 1))) + LIST(el(0, li(5)) + el(2, lp(3)))
             + SPARSE(fstr(7, "x")) + HOLDER(hu(fstr(1, "x")) + scalar_u(1, 1)) + TRAILER(9))
    canon("m_composite", whole)
    # A prefix of a valid message is complete or incomplete, never INVALID (§7).
    for cut in range(1, len(whole)):
        add(f"m_composite_prefix_{cut:03d}", whole[:cut], "not_reject")

    if out_dir is not None:
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):
            if f.endswith(".bin"):
                os.remove(os.path.join(out_dir, f))
        for name, data, _ in V:
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(data)
    return V


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/union-deep"
    v = emit_union_deep(out)
    by = {}
    for _, _, e in v:
        k = "same" if e.startswith("same:") else e
        by[k] = by.get(k, 0) + 1
    print(f"[union-deep] {len(v)} vectors -> {out}: "
          + ", ".join(f"{k}={n}" for k, n in sorted(by.items())))


if __name__ == "__main__":
    main()
