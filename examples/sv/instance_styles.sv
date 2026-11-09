// Different module instantiation styles
module instance_styles (
  input  logic       clk,
  input  logic       rst_n,
  input  logic [7:0] a,
  output logic [7:0] y
);
  logic [7:0] tmp0, tmp1;

  // named connections
  sub u_named (
    .clk  (clk),
    .rst_n(rst_n),
    .d    (a),
    .q    (tmp0)
  );

  // ordered connections
  sub u_ordered (clk, rst_n, tmp0, tmp1);

  // parameter override, unconnected port and implicit connection
  sub #(.WIDTH(8), .DEPTH(4)) u_param (
    .clk,
    .rst_n,
    .d (tmp1),
    .q (),
    .unused ()
  );

  // ordered parameter override
  sub #(8) u_param_ordered (.clk(clk), .rst_n(rst_n), .d(tmp1), .q(y));

  // expressions in connections
  sub u_expr (
    .clk  (clk),
    .rst_n(rst_n & en),
    .d    ({a[3:0], a[7:4]}),
    .q    (tmp1[7:0])
  );

  // wildcard connection
  sub u_wild (.*);
endmodule
