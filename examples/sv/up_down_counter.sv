//-----------------------------------------------------
// Design Name : up_down_counter
// File Name   : up_down_counter.sv
// Function    : Up down counter
// Coder      : Deepak
//-----------------------------------------------------
module up_down_counter    (
output reg  [7:0] out      ,  // Output of the counter
input  wire       up_down  ,  // up_down control for counter
input  wire       clk      ,  // clock input
input  wire       reset       // reset input
);

//-------------Code Starts Here-------
always_ff @(posedge clk)
if (reset) begin // active high reset
  out <= 8'b0 ;
end else if (up_down) begin
  out ++;
end else begin
  out --;
end

endmodule
