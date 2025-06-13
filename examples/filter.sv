// ======================
// Filter Wrapper
// ======================
module filter (
    input  logic clk,
    input  logic reset_n,
    input  logic [7:0] raw_data,
    output logic [7:0] filtered_data
);
    // Instance of the FIR filter
    fir_filter fir_inst (
        .clk(clk),
        .reset_n(reset_n),
        .data_in(raw_data),
        .data_out(filtered_data)
    );
endmodule
