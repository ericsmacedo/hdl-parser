
`ifdef MOD
module ifdef_example #(
`ifdef BAR
  parameter PARAM0 = 0, // Parameter PARAM0
`endif
  parameter PARAM1 = 0 // Parameter PARAM1
) (
    input  a_i, // Input a
`ifdef FOO
    input  b_i, // Input b
`ifdef BAZ
    input  c_i, // Input c
`endif
    input  d_i, // Input d
`endif
    input  e_i, // Input e
    output x_o  // Output x
);

endmodule
`endif
