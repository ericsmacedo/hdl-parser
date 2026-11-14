// `ifdef around ports, parameters and instances.
//
// 'FEATURE_A' and 'TECH_FPGA' are defined here, all other conditions are unknown.
`define FEATURE_A
`define TECH_FPGA

module cond_ports #(
    parameter int WIDTH = 8,

    parameter int A_DEPTH = 16,

`ifdef FEATURE_B
    parameter int B_DEPTH = 32,
`endif
    parameter bit LAST = 1'b0
) (
    input  logic clk_i,

    input  logic [WIDTH-1:0] a_i, // only with feature A


`ifdef FEATURE_B
    input  logic [WIDTH-1:0] b_i, // only with feature B
  
    input  logic a_and_b_i,
  
`endif
`ifdef TECH_ASIC
    input  logic scan_en_i,
`else
    input  logic fpga_cfg_i,
`endif
`ifdef TECH_SIM
    input  logic sim_only_i,
`else
    input  logic sim_or_fpga_i,
`endif
    output logic [WIDTH-1:0] q_o
);


    fpga_ram u_ram (.clk_i(clk_i));


`ifndef SYNTHESIS
    checker_mod u_checker (.clk_i(clk_i));
`endif

endmodule



`ifdef FEATURE_B
module only_with_b (input logic y);
endmodule
`endif
