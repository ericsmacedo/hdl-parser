// A define of the project configuration selects the definition of the bus macro.
//
// With `ifdef resolution the AXI4-Lite ports are found, as 'USE_AXI' is defined in 'config.svh'.
// Without, the macro 'REG_BUS_PORTS' is ambiguous and stays unresolved.
//
// 'DEBUG_PORTS' stays unresolved in any case: 'DEBUG' is not defined in the sources, but it may be defined by the
// build flow. Hand it over (or a macro file without it) to get a result.
`include "config.svh"

module bus_select #(
    parameter string BUS = `REG_BUS_NAME
) (
    input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */,
    `REG_BUS_PORTS(reg),
    `DEBUG_PORTS
    output logic [(32)-1:0] data_o [4]
);

endmodule
