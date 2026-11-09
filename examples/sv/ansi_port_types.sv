// ANSI-style ports with net, variable, signing and dimension variants
module ansi_port_types (
  input                    clk,          // implicit net
  input  wire              rst_n,        // explicit net
  input  logic             en,
  input  var logic         sel,
  input  tri               bus_tri,
  input  signed     [7:0]  s_data,       // signed, implicit type
  input  logic signed [7:0] ls_data,
  input  logic unsigned [7:0] lu_data,
  input  bit        [3:0]  b_data,
  input  int               count,
  input  logic      [3:0]  a, b, c,      // multiple names, shared type
  input  logic      [7:0][3:0] packed2d,
  input  logic      [7:0]  mem [4],
  input  logic             mem2d [2][3],
  output logic      [7:0]  q [0:3],
  output reg               r,
  inout  wire       [1:0]  pads
);
endmodule
