

module ifdef_elif_95 (a_i,
`ifndef FOO
  b_i,
`else
  c_i,
`endif
  d_i, e_i,
  f_i,
  x_o
)
`ifdef BAR
  parameter PARAM0 = 0; // Parameter PARAM0
`elsif BAR2
  parameter PARAM3 = 0; // Parameter PARAM3
`elsif BAR3
  parameter PARAM4 = 0; // Parameter PARAM3
`endif
`ifdef VALUE
  parameter PARAM7 = 1;
`else
  parameter PARAM7 = 3;
`endif
`ifdef DEFAULT
  parameter PARAM7 = `DEFAULT;
`else
  parameter PARAM7 = 3;
`endif
  parameter PARAM1 = 0; // Parameter PARAM1
  input  a_i; // Input a
`ifndef FOO
  input  b_i; // Input b
`else
  input  c_i; // Input c
`endif
  input  d_i; // Input d
  input  e_i; // Input e
`ifdef VALUE
  input [1:0] f_i;
`else
  input [3:0] f_i;
`endif
    output x_o; // Output x
);


endmodule
