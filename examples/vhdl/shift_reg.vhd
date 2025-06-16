library ieee;
use ieee.std_logic_1164.all;

entity shift_reg is
    generic (
        WIDTH   : positive := 8
    );
    port (
        rst     : in  std_logic;
        clk     : in  std_logic;
        load    : in  std_logic;
        lsb     : in  std_logic;
        output  : out std_logic_vector(WIDTH-1 downto 0)
    );
end shift_reg;

architecture BHV of shift_reg is
    signal reg : std_logic_vector(WIDTH-1 downto 0);
begin
    
    process(clk, rst, load, lsb)
    begin
        if(rst = '1') then
            -- Reset to default value
            reg <= (others => '0');
        elsif(rising_edge(clk)) then
            if(load = '1') then
                reg <= reg(WIDTH-2 downto 0) & lsb; -- shift in the new LSB
            else
                reg <= reg;
            end if;
        end if;       
    end process;
    
    -- Break out the register's value
    output <= reg;
    
end BHV;
