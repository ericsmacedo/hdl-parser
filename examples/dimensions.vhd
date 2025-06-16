entity my_entity_0 is
    port (
        -- 8-bit input
        data_in : in std_logic_vector(7 downto 0);
 
        -- 16-bit input
        address : in std_logic_vector(15 downto 0)
    );
end entity my_entity_0;

entity my_entity_1 is
    port (
        -- Integer input with range 0 to 255 (8-bit equivalent)
        count_value : in integer range 0 to 255
    );
end entity my_entity_1;

entity my_entity_2 is
    generic (
        WIDTH : integer := 8  -- Default width is 8 bits
    );
    port (
        data_in : in std_logic_vector(WIDTH-1 downto 0)
    );
end entity my_entity_2;
