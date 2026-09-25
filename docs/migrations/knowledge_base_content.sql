-- Knowledge base: articles authored inside NoHarm
--
-- base_conhecimento used to hold only pointers to articles written in ODOO.
-- Articles can now be written here: the content lives in "conteudo" (HTML from
-- the rich text editor), "link" becomes optional (an article may have content,
-- a link, or both) and "secao" pins an article to sections of a screen, the way
-- "pagina" pins it to whole screens.
--
-- Mirror this change in noharm-ai/database (noharm-public.sql) so CI and new
-- installations get the same table.

ALTER TABLE public.base_conhecimento ALTER COLUMN link DROP NOT NULL;
ALTER TABLE public.base_conhecimento ADD COLUMN IF NOT EXISTS secao varchar(255)[] NULL;
ALTER TABLE public.base_conhecimento ADD COLUMN IF NOT EXISTS conteudo text NULL;

-- Training lessons (treinamento_item) that complement the article
ALTER TABLE public.base_conhecimento ADD COLUMN IF NOT EXISTS treinamento_item integer[] NULL;
