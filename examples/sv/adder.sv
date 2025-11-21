`timescale 1ns/1ps

module adder #(
  parameter integer DATA_WIDTH = 8,    // Width of input operands
  parameter integer OUTPUT_WIDTH = 4   // Test configuration value
) (
  input  logic unsigned [DATA_WIDTH-1:0] A,      // Packed input operand A
  input  logic unsigned [DATA_WIDTH-1:0] B,      // Packed input operand B
  output logic unsigned [DATA_WIDTH:0]   X,      // Packed sum output
  input  logic        [7:0]              byte_p, // Packed byte input
  input  logic        [3:0][7:0]         word_p, // Packed 32-bit word (4 bytes)
  input  logic                           flag_u, // Unpacked single bit
  input  logic        [7:0]              arr_u [0:3] // Unpacked byte array
);

  assign X = A + B;

  logic a_port; // Test port A
  logic b_port; // Test port B
  assign a_port = 'd0;

  test_module u_test_module(
      .test_input(a_port),  // Connected to a_port
      .test_output(b_port)  // Connected to b_port
      );

  // Dump waves
  initial begin
    $dumpfile("dump.vcd");
    $dumpvars(1, adder);
  end

endmodule
