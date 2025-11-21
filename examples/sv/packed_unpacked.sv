// This file is public domain, it can be freely copied without restrictions.
// SPDX-License-Identifier: CC0-1.0
// Adder DUT
`timescale 1ns/1ps

module packed_unpacked #(
  parameter  [4:0] P_VEC = 0,
  parameter  [4:0][3:0] P_MATRIX = 0,
  parameter  P_UNPACK [4:0] = 0,
  parameter  [3:0] P_VEC_UNPACK [4:0] = 0
)(
  input  [4:0] vec_i,
  input  [4:0][3:0] matrix_i,
  input  unpack_i [4:0],
  input  [3:0] vec_unpack_i [4:0],
  output out_o
);


endmodule
