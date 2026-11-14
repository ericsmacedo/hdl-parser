// The name of a condition is built from an argument of the macro.
`define HAS_UART
`define HAS_SPI

// A port, if the related feature is enabled
`define OPT_PORT(feature, port) \
`ifdef HAS_``feature \
    port, \
`endif

// The argument is the name of the condition
`define IF_DEFINED(name, port) \
`ifdef ``name \
    port, \
`endif

// The feature selects the implementation
`define IMPL(feature) \
`ifdef HAS_``feature \
    feature``_core u_``feature (.clk_i(clk_i)); \
`else \
    feature``_stub u_``feature (.clk_i(clk_i)); \
`endif

module cond_pasted (
    input  logic clk_i,
    `OPT_PORT(UART, output logic uart_tx_o)
    `OPT_PORT(SPI, output logic spi_clk_o)
    `OPT_PORT(I2C, inout wire i2c_sda_io)
    `IF_DEFINED(HAS_UART, input logic uart_rx_i)
    `IF_DEFINED(HAS_CAN, input logic can_rx_i)
    output logic irq_o
);
    `IMPL(UART)
    `IMPL(I2C)
endmodule
