// A define of the project configuration selects the definition of the bus macro.
//
// With `ifdef resolution the AXI4-Lite ports are found, as 'USE_AXI' is defined in 'config.svh'.
// Without, the macro 'REG_BUS_PORTS' is ambiguous and stays unresolved.
//
// 'DEBUG_PORTS' stays unresolved in any case: 'DEBUG' is not defined in the sources, but it may be defined by the
// build flow. Hand it over (or a macro file without it) to get a result.
`include "config.svh"

module bus_select #(
    parameter string BUS = "axi4-lite"
) (
    input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */,
    input  logic                  reg_awvalid_i, 
    output logic                  reg_awready_o, 
    input  logic [(16)-1:0]       reg_awaddr_i, 
    input  logic                  reg_wvalid_i, 
    output logic                  reg_wready_o, 
    input  logic [31:0]           reg_wdata_i, 
    output logic                  reg_bvalid_o, 
    input  logic                  reg_bready_i,
    `DEBUG_PORTS
    output logic [(32)-1:0] data_o [4]
);

endmodule
