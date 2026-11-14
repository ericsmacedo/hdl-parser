// `ifdef around ports, parameters and instances.
//
// 'FEATURE_A' and 'TECH_FPGA' are defined here, all other conditions are unknown.
`define FEATURE_A
`define TECH_FPGA

module cond_ports #(
    parameter int WIDTH = 8,
`ifdef FEATURE_A
    parameter int A_DEPTH = 16,
`else
    parameter int NO_A = 1,
`endif
`ifdef FEATURE_B
    parameter int B_DEPTH = 32,
`endif
    parameter bit LAST = 1'b0
) (
    input  logic clk_i,
`ifdef FEATURE_A
    input  logic [WIDTH-1:0] a_i, // only with feature A
`else
    input  logic no_a_i,
`endif
`ifndef FEATURE_A
    input  logic no_a2_i,
`endif
`ifdef FEATURE_B
    input  logic [WIDTH-1:0] b_i, // only with feature B
  `ifdef FEATURE_A
    input  logic a_and_b_i,
  `else
    input  logic b_without_a_i,
  `endif
`endif
`ifdef TECH_ASIC
    input  logic scan_en_i,
`elsif TECH_FPGA
    input  logic fpga_cfg_i,
`elsif TECH_SIM
    input  logic sim_ctrl_i,
`else
    input  logic generic_i,
`endif
`ifdef TECH_SIM
    input  logic sim_only_i,
`elsif TECH_FPGA
    input  logic sim_or_fpga_i,
`else
    input  logic not_sim_not_fpga_i,
`endif
    output logic [WIDTH-1:0] q_o
);

`ifdef TECH_FPGA
    fpga_ram u_ram (.clk_i(clk_i));
`else
    asic_ram u_ram (.clk_i(clk_i));
`endif

`ifndef SYNTHESIS
    checker_mod u_checker (.clk_i(clk_i));
`endif

endmodule

`ifndef FEATURE_A
module only_without_a (input logic x);
endmodule
`endif

`ifdef FEATURE_B
module only_with_b (input logic y);
endmodule
`endif
