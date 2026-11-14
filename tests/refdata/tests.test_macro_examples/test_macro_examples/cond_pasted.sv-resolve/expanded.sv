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
     
    output logic uart_tx_o, 

     
    output logic spi_clk_o, 

    `ifdef HAS_I2C 
    inout wire i2c_sda_io, 
`endif
     
    input logic uart_rx_i, 

    `ifdef HAS_CAN 
    input logic can_rx_i, 
`endif
    output logic irq_o
);
     
    UART_core u_UART (.clk_i(clk_i)); 

    `ifdef HAS_I2C 
    I2C_core u_I2C (.clk_i(clk_i)); 
`else 
    I2C_stub u_I2C (.clk_i(clk_i)); 
`endif
endmodule
