library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity decoder is
    generic (
        SELBITS : positive := 2
    );
    port (
        en  : in  std_logic;
        sel : in  std_logic_vector(SELBITS-1 downto 0);
        hot : out std_logic_vector(2**SELBITS-1 downto 0)
    );
end decoder;

architecture BHV of decoder is
begin
    process(en, sel)
    begin
        hot <= (others => '0');
        if(en = '1') then
            hot(to_integer(unsigned(sel))) <= '1';
        end if;
    end process;
end BHV;
