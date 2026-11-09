// Instances inside generate blocks and procedural code
module generate_blocks #(
  parameter int N = 4
) (
  input  logic         clk,
  input  logic [N-1:0] d,
  output logic [N-1:0] q
);
  genvar i;
  generate
    for (i = 0; i < N; i++) begin : g_bit
      dff u_dff (.clk(clk), .d(d[i]), .q(q[i]));
    end
  endgenerate

  if (N > 2) begin : g_extra
    extra u_extra (.clk(clk));
  end

  always_ff @(posedge clk) begin
    if (d[0]) begin
      $display("d0 set");
    end
  end

  function automatic logic parity(input logic [N-1:0] v);
    return ^v;
  endfunction
endmodule
