// Verilog-2001 non-ANSI port declarations
module non_ansi_ports (clk, rst_n, d, q, valid, bus);
  input        clk;   // clock
  input        rst_n; // reset
  input  [7:0] d;
  output [7:0] q;
  output       valid;
  inout  [3:0] bus;

  reg [7:0] q;
  reg       valid;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      q     <= 8'h00;
      valid <= 1'b0;
    end else begin
      q     <= d;
      valid <= 1'b1;
    end
  end
endmodule
