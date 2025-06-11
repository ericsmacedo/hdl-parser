// ======================
// FIR Filter (Leaf Module)
// ======================
module fir_filter (
    input  logic clk,
    input  logic reset_n,
    input  logic [7:0] data_in,
    output logic [7:0] data_out
);
    // Simple FIR filter implementation (example: moving average)
    logic [7:0] shift_reg [0:3];
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            shift_reg <= '{default: 0};
            data_out <= 0;
        end else begin
            shift_reg <= {data_in, shift_reg[0:2]};
            data_out <= (shift_reg[0] + shift_reg[1] + shift_reg[2] + shift_reg[3]) >> 2;
        end
    end
endmodule
