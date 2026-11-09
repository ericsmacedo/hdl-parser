// Plain Verilog-2001 file
`timescale 1ns/1ps
`define WIDTH 8

module verilog_2001 #(parameter WIDTH = `WIDTH) (
  input  wire             clk,
  input  wire [WIDTH-1:0] din,
  output reg  [WIDTH-1:0] dout
);
  always @(posedge clk)
    dout <= din;
endmodule
