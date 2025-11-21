

module ifdef_elif_example #(
`ifdef BAR
  parameter PARAM0 = 0, // Parameter PARAM0
`elsif BAR2
   parameter PARAM3 = 0, // Parameter PARAM3
`elsif BAR3
   parameter PARAM4 = 0, // Parameter PARAM3
`endif
  parameter PARAM1 = 0 // Parameter PARAM1
) (
    input  a_i, // Input a
`ifndef FOO
    input  b_i, // Input b
`else
    input  c_i, // Input c
`endif
    input  d_i, // Input d
    input  e_i, // Input e
    output x_o  // Output x
);


endmodule
