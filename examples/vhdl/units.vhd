-- A file may contain packages, several entities and several architectures per entity
library ieee;
use ieee.std_logic_1164.all;

package units_pkg is

  constant WIDTH : natural := 8;

  component leaf is
    port (
      a : in  std_logic;
      y : out std_logic
    );
  end component leaf;

  function invert (value : std_logic) return std_logic;

end package units_pkg;

package body units_pkg is

  function invert (value : std_logic) return std_logic is
  begin
    return not value;
  end function invert;

end package body units_pkg;

library ieee;
use ieee.std_logic_1164.all;

ENTITY Leaf IS
  PORT (
    A : IN  STD_LOGIC;
    Y : OUT STD_LOGIC
  );
END ENTITY Leaf;

ARCHITECTURE Rtl OF Leaf IS
BEGIN
  Y <= NOT A;
END ARCHITECTURE Rtl;

library ieee;
use ieee.std_logic_1164.all;
use work.units_pkg.all;

entity branch is
  port (
    a : in  std_logic;
    y : out std_logic
  );
end branch;

-- First architecture
architecture structural of branch is
  signal mid : std_logic;
begin
  u_leaf0 : leaf port map (a => a, y => mid);
  u_leaf1 : leaf port map (a => mid, y => y);
end structural;

-- Second architecture of the same entity
architecture behavioral of branch is
begin
  y <= a;
end behavioral;

configuration branch_cfg of branch is
  for structural
    for all : leaf
      use entity work.leaf(rtl);
    end for;
  end for;
end configuration branch_cfg;
