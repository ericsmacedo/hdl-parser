// Test module with parameters and instantiations
`timescale 1ns/1ps

module param_module
import test_pack::*;
#(
    parameter WIDTH = 8, // Width of the input data
    parameter DEPTH = 4,
    parameter [7:0] INIT_VAL = 8'hFF,
    parameter logic ENABLE_FEATURE = 1'b1
) (
    input wire clk,
    input wire rst_n,  // active-low reset
    input wire [WIDTH-1:0] data_in, // Input data
    // other comment
    output reg [WIDTH-1:0] data_out,
    inout wire [DEPTH-1:0] bidir_bus
);

    // Internal signals
    logic [WIDTH-1:0] internal_reg;
    wire [DEPTH-1:0] internal_wire;

    // Submodule instantiation
    sub_module #(
        .DATA_WIDTH(WIDTH),
        .INIT_VALUE(INIT_VAL)
    ) u_sub_module (
        .clk(clk), // comment
        // other comment
        .reset(rst_n),
        .input_data(data_in),
        .output_data(internal_wire),
        .config_bus(bidir_bus)
    );

    // Another instance with different parameters
    sub_module #(
        .DATA_WIDTH(4),
        .INIT_VALUE(8'h0F)
    ) u_sub_module2 (
        .clk(clk),
        .reset(rst_n),
        .input_data(data_in[3:0]),
        .output_data(),
        .config_bus(bidir_bus[1:0])
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_out <= INIT_VAL;
            internal_reg <= '0;
        end
        else if (ENABLE_FEATURE) begin
            data_out <= internal_wire;
            internal_reg <= data_in;
        end
    end

    //================
    `ifndef SYNTHESIS
       if (DOUT_OVR == SAT_SYM && DOUT_ENC == UNSIGNED)
            $error("DOA=SAT_SYM is not SDASDSADSAD");
       if ()

    `endif

endmodule

// Submodule definition
module sub_module #(
    parameter DATA_WIDTH = 8,
    parameter [7:0] INIT_VALUE = 0
)(
    input wire clk,
    input wire reset,
    input wire [DATA_WIDTH-1:0] input_data,
    output wire [DATA_WIDTH-1:0] output_data,
    inout wire [DATA_WIDTH/2-1:0] config_bus
);
    // Implementation would go here
endmodule
