library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.bus_pkg.all;

entity port_types is
  generic (
    ADDR_WIDTH : natural := 8
  );
  port (
    clk_i    : in    std_logic; -- Clock
    rst_an_i : in    std_logic := '1'; -- Reset with default value
    -- Arithmetic types
    count_o  : out   unsigned(ADDR_WIDTH - 1 downto 0);
    offset_i : in    signed(clog2(ADDR_WIDTH) - 1 downto 0); -- Function call within the range
    level_i  : in    integer range 0 to 255;
    gain_i   : in    real;
    -- Ascending range
    mask_i   : in    bit_vector(0 to 7);
    -- Types of a package
    req_i    : in    work.bus_pkg.req_t;
    rsp_o    : out   rsp_t;
    -- Array of vectors (VHDL-2008)
    mem_o    : out   slv_array_t(0 to 3)(15 downto 0);
    -- Other modes
    data_io  : inout std_logic_vector(7 downto 0);
    state_o  : buffer std_logic_vector(1 downto 0);
    -- No mode is 'in'
    enable   : std_logic
  );
end port_types;
