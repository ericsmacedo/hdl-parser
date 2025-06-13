// ======================
// Data Processor
// ======================
module data_processor (
    input  logic clk,
    input  logic reset_n,
    input  logic [7:0] sensor_data,
    output logic [7:0] processed_data
);
    // Instance of the filter module
    filter filter_inst (
        .clk(clk),
        .reset_n(reset_n),
        .raw_data(sensor_data),
        .filtered_data(processed_data)
    );
endmodule
