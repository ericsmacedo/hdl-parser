// Ports defined by macros with arguments, defaults and token pasting.
`include "bus.svh"

module port_macros #(
    parameter int IN_WIDTH  = 16,
    parameter int OUT_WIDTH = 8
) (
    input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */,
    input logic             in_valid, 
    input logic [(IN_WIDTH)-1:0]       in_data, 
    output logic             in_ready,
    output logic             out_valid, 
    output logic [(OUT_WIDTH)-1:0]       out_data, 
    input logic             out_ready,
    input logic             aux_valid, 
    input logic [(8)-1:0]       aux_data, 
    output logic             aux_ready,
    input  logic                  cfg_psel_i,    /* Select */ 
    input  logic                  cfg_penable_i, /* Enable */ 
    input  logic                  cfg_pwrite_i,  /* Write */ 
    input  logic [(12)-1:0]       cfg_paddr_i,   /* Address */ 
    input  logic [31:0]           cfg_pwdata_i,  /* Write Data */ 
    output logic [31:0]           cfg_prdata_o,  /* Read Data */ 
    output logic                  cfg_pready_o   /* Ready */,
    output logic busy_o // Busy
);

endmodule
