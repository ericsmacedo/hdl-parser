// Module with multiple unpacked ports declared in one line
module multi_unpacked_ports #(
    parameter [3:0] WIDTH = 4'b1010,  // 4-bit packed
    parameter integer CONFIG [0:2] = '{8, 16, 32}  // 3-element unpacked array
) (
    input  wire [7:0]                  data_in,       // 8-bit packed
    output logic [WIDTH-1:0]           data_out,      // Dynamic width (from parameter)

    input  wire [15:0]                 mem_a [0:7], mem_b [0:7],  // Two 8-entry memories (16-bit each)
    output reg  [31:0]                 result_x [0:3], result_y [0:3],  // Two 4-entry arrays (32-bit each)

    input  logic [1:0][3:0]            packed_unpacked [0:1]  // 2-element unpacked, each 2x4 packed
);

    // Internal unpacked arrays (declared in one line)
    integer idx [0:3], idy [0:3];  // Two 4-element integer arrays

    // Combinational logic (packed operation)
    always_comb begin
        data_out = data_in[3:0] ^ WIDTH;  // XOR with parameter
    end

    // Sequential logic (unpacked operations)
    always_ff @(posedge clk) begin
        for (int i = 0; i < 4; i++) begin
            // Sum two unpacked input memories
            result_x[i] <= mem_a[i*2] + mem_b[i*2];
            result_y[i] <= mem_a[i*2+1] - mem_b[i*2+1];
        end
    end

endmodule

// Testbench with instantiation
module tb ();
    // Test signals
    logic [7:0]        data_in = 8'hA5;
    logic [3:0]        data_out;
    wire  [15:0]       mem_a [0:7] = '{16'h1111, 16'h2222, 16'h3333, 16'h4444, 
                                      16'h5555, 16'h6666, 16'h7777, 16'h8888};
    wire  [15:0]       mem_b [0:7] = '{16'h0001, 16'h0002, 16'h0003, 16'h0004, 
                                      16'h0005, 16'h0006, 16'h0007, 16'h0008};
    logic [31:0]       result_x [0:3], result_y [0:3];
    logic [1:0][3:0]   packed_unpacked [0:1] = '{8'h12, 8'h34};

    // Clock
    reg clk = 0;
    always #5 clk = ~clk;

    // Instantiate the module
    multi_unpacked_ports #(
        .WIDTH(4'b1100),
        .CONFIG('{4, 12, 24})
    ) dut (
        .data_in(data_in),
        .data_out(data_out),
        .mem_a(mem_a), 
        .mem_b(mem_b),  // Unpacked ports connected in bulk
        .result_x(result_x), 
        .result_y(result_y),
        .packed_unpacked(packed_unpacked)
    );

    // Monitor results
    initial begin
        $monitor("At time %0t: data_out = %h", $time, data_out);
        #100 $finish;
    end
endmodule
