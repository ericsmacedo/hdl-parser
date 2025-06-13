// ======================
// Sensor Interface
// ======================
module sensor_interface (
    input  logic clk,
    input  logic reset_n,
    input  logic [7:0] sensor_input,
    output logic [7:0] data_valid
);
    // Simple input synchronization
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n)
            data_valid <= 0;
        else
            data_valid <= sensor_input;
    end
endmodule
