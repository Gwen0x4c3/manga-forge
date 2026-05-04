-- MangaForge MySQL initialization
-- Character set and collation
ALTER DATABASE mangaforge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Grant privileges
GRANT ALL PRIVILEGES ON mangaforge.* TO 'mangaforge'@'%';
FLUSH PRIVILEGES;
