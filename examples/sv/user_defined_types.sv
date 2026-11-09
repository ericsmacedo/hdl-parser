// Ports using user-defined, package-scoped and type-parameter types
module user_defined_types #(
  parameter type T = logic [7:0],
  parameter int  N = 4
) (
  input  logic          clk,
  input  T              data_i,
  input  my_pkg::req_t  req_i,
  output my_pkg::rsp_t  rsp_o,
  output state_t [1:0]  state_o,
  output T              data_o [N]
);
endmodule
