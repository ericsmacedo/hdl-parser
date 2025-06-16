library ieee;
use ieee.std_logic_1164.all;

entity mux_2x1 is
    generic (
        WIDTH : positive := 1
    );
    port (
        output : out std_logic_vector(WIDTH-1 downto 0);
        sel    : in  std_logic;
        in0    : in  std_logic_vector(WIDTH-1 downto 0);
        in1    : in  std_logic_vector(WIDTH-1 downto 0)
    );
end mux_2x1;

architecture BHV of mux_2x1 is
begin
    
    output <=
        in0 when sel = '0' else
        in1 when sel = '1' else
        (others => '0');
    
end BHV;
