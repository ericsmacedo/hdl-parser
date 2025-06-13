// ======================
// Top Module: Sensor System
// ======================
module sensor_system (
    input  logic clk,
    input  logic reset_n,
    input  logic [7:0] sensor_input,
    output logic [7:0] final_output
);
    // Internal signals
    logic [7:0] interface_to_processor;

    // Instance of sensor_interface
    sensor_interface interface_inst (
        .clk(clk),
        .reset_n(reset_n),
        .sensor_input(sensor_input),
        .data_valid(interface_to_processor)
    );

    // Instance of data_processor (with nested hierarchy)
    data_processor processor_inst (
        .clk(clk),
        .reset_n(reset_n),
        .sensor_data(interface_to_processor),
        .processed_data(final_output)
    );
endmodule
