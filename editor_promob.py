import sys
import traceback
import unicodedata
import shutil

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, filedialog
    import xml.etree.ElementTree as ET
    import os
except Exception as e:
    with open("log_erro_importacao.txt", "w") as f:
        f.write(f"Erro ao importar bibliotecas: {str(e)}\n")
        f.write(traceback.format_exc())
    print("ERRO CRITICO DE IMPORTACAO. Veja log_erro_importacao.txt")
    sys.exit(1)

# Pillow é opcional: sem ele só PNG/GIF são exibidos
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


class PromobSetupManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Gerenciador de Setups Promob - ProTech (Filtro Avançado)")
        self.root.geometry("1400x900")

        self.system_path = None
        self.atributos_path = None
        self.config_path = None
        self.index_path = None
        self.property_path = None

        self.db_vars = {}
        self.db_values = {}
        self.map_cat_vars = {}
        self.map_path_vars = {}
        self.cat_names = {}
        self.cat_images = {}
        self.cat_img_attrs = {}
        self.image_cache = {}
        self.full_image_cache = {}
        self.image_file_index = None
        self.last_image_error = ""

        self.available_setups = {}
        self.current_setup_id = None

        self.inline_editor = None

        # Controle de edição do nome do setup direto no combobox
        self.last_setup_text = ""
        self.suppress_setup_edit = False

        self.create_top_header()

        self.paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.frame_left = ttk.LabelFrame(self.paned, text="Categorias (Property)")
        self.paned.add(self.frame_left, weight=1)

        # Treeview de categorias com scrollbar
        tree_container = ttk.Frame(self.frame_left)
        tree_container.pack(fill=tk.BOTH, expand=True)
        self.tree_cats = ttk.Treeview(tree_container, show="tree", selectmode="browse")
        self.scroll_cats = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree_cats.yview)
        self.tree_cats.configure(yscrollcommand=self.scroll_cats.set)
        self.tree_cats.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scroll_cats.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_cats.bind("<<TreeviewSelect>>", self.on_category_select)

        btn_show_img = ttk.Button(self.frame_left, text="🖼️ Ver imagem da categoria", command=self.show_selected_category_image)
        btn_show_img.pack(fill=tk.X, padx=5, pady=5)

        self.frame_right = ttk.LabelFrame(self.paned, text="Variáveis do Setup")
        self.paned.add(self.frame_right, weight=3)

        self.create_advanced_filter_area()
        self.create_table()
        self.create_footer_actions()

    def copy_to_clipboard(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception:
            pass

    def create_top_header(self):
        header = ttk.Frame(self.root, relief=tk.RAISED, borderwidth=1)
        header.pack(fill=tk.X, side=tk.TOP, padx=5, pady=5)

        btn_folder = ttk.Button(header, text="📂 1. Selecionar Pasta 'System'", command=self.select_system_folder)
        btn_folder.pack(side=tk.LEFT, padx=10, pady=10)

        self.lbl_status_folder = ttk.Label(header, text="Aguardando...", foreground="red")
        self.lbl_status_folder.pack(side=tk.LEFT, pady=10)

        ttk.Separator(header, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=15, pady=5)

        ttk.Label(header, text="Setup Ativo:").pack(side=tk.LEFT)

        self.cb_setups = ttk.Combobox(header, state="normal", width=80)
        self.cb_setups.pack(side=tk.LEFT, padx=5)
        self.cb_setups.bind("<<ComboboxSelected>>", self.on_setup_change)
        self.cb_setups.bind("<Control-c>", self.copy_setup_name)
        self.cb_setups.bind("<FocusOut>", self.on_setup_edit_finish)
        self.cb_setups.bind("<Return>", self.on_setup_edit_finish)

        btn_dup = ttk.Button(header, text="➕ Novo Setup", command=self.duplicate_setup_dialog)
        btn_dup.pack(side=tk.LEFT, padx=10)

        btn_ren = ttk.Button(header, text="✏️ Renomear Setup", command=self.rename_setup_dialog)
        btn_ren.pack(side=tk.LEFT, padx=10)

        btn_del = ttk.Button(header, text="🗑 Deletar Setup", command=self.delete_setup)
        btn_del.pack(side=tk.LEFT, padx=10)

        fr_agent = ttk.Frame(header, relief=tk.GROOVE, borderwidth=1)
        fr_agent.pack(side=tk.RIGHT, padx=10, pady=5)
        ttk.Label(fr_agent, text="🤖 Agente Global:").pack(side=tk.LEFT)
        self.entry_agent = ttk.Entry(fr_agent, width=20)
        self.entry_agent.pack(side=tk.LEFT, padx=5)
        self.entry_agent.bind("<Return>", self.run_agent_search)
        ttk.Button(fr_agent, text="Buscar", command=self.run_agent_search).pack(side=tk.LEFT)

    def create_advanced_filter_area(self):
        self.filter_frame = ttk.LabelFrame(self.frame_right, text="Filtros Combinados (Busca na Categoria + Subcategorias)")
        self.filter_frame.pack(fill=tk.X, padx=5, pady=5)
        for i in range(6):
            self.filter_frame.columnconfigure(i, weight=1)

        ttk.Label(self.filter_frame, text="ID:").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Label(self.filter_frame, text="Nome:").grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(self.filter_frame, text="Categoria:").grid(row=0, column=2, sticky="w", padx=5)
        ttk.Label(self.filter_frame, text="Valor:").grid(row=0, column=3, sticky="w", padx=5)
        ttk.Label(self.filter_frame, text="Descrição:").grid(row=0, column=4, sticky="w", padx=5)

        self.ent_f_id = ttk.Entry(self.filter_frame); self.ent_f_id.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5)); self.ent_f_id.bind("<KeyRelease>", self.on_advanced_search)
        self.ent_f_name = ttk.Entry(self.filter_frame); self.ent_f_name.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 5)); self.ent_f_name.bind("<KeyRelease>", self.on_advanced_search)
        self.ent_f_cat = ttk.Entry(self.filter_frame); self.ent_f_cat.grid(row=1, column=2, sticky="ew", padx=5, pady=(0, 5)); self.ent_f_cat.bind("<KeyRelease>", self.on_advanced_search)
        self.ent_f_val = ttk.Entry(self.filter_frame); self.ent_f_val.grid(row=1, column=3, sticky="ew", padx=5, pady=(0, 5)); self.ent_f_val.bind("<KeyRelease>", self.on_advanced_search)
        self.ent_f_desc = ttk.Entry(self.filter_frame); self.ent_f_desc.grid(row=1, column=4, sticky="ew", padx=5, pady=(0, 5)); self.ent_f_desc.bind("<KeyRelease>", self.on_advanced_search)

        ttk.Button(self.filter_frame, text="🧹 Limpar", command=self.clear_filters).grid(row=1, column=5, padx=5, pady=(0, 5))

    def create_table(self):
        cols = ("ID", "Nome", "Categoria", "Valor Atual", "Padrão", "Descrição", "Score")
        self.tree_vars = ttk.Treeview(self.frame_right, columns=cols, show="headings", selectmode="extended")
        self.tree_vars.heading("ID", text="ID"); self.tree_vars.column("ID", width=120)
        self.tree_vars.heading("Nome", text="Nome Variável"); self.tree_vars.column("Nome", width=200)
        self.tree_vars.heading("Categoria", text="Categoria"); self.tree_vars.column("Categoria", width=150)
        self.tree_vars.heading("Valor Atual", text="Valor"); self.tree_vars.column("Valor Atual", width=80)
        self.tree_vars.heading("Padrão", text="Default"); self.tree_vars.column("Padrão", width=80)
        self.tree_vars.heading("Descrição", text="Descrição Técnica"); self.tree_vars.column("Descrição", width=300)
        self.tree_vars.heading("Score", text="Relevância"); self.tree_vars.column("Score", width=50, anchor="center")

        self.scroll_vars = ttk.Scrollbar(self.frame_right, orient="vertical", command=self.tree_vars.yview)
        self.tree_vars.configure(yscrollcommand=self.scroll_vars.set)
        self.tree_vars.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.scroll_vars.pack(side=tk.RIGHT, fill=tk.Y, in_=self.tree_vars)

        self.tree_vars.bind("<Double-1>", self.on_double_click_var)
        self.tree_vars.bind("<Tab>", self.on_tab_edit_next)
        self.tree_vars.bind("<Shift-Tab>", self.on_shift_tab_edit_prev)
        self.tree_vars.bind("<ISO_Left_Tab>", self.on_shift_tab_edit_prev)
        self.tree_vars.bind("<Control-c>", self.copy_var_info)

    def create_footer_actions(self):
        frame = ttk.Frame(self.frame_right)
        frame.pack(fill=tk.X, padx=5, pady=10)
        ttk.Label(frame, text="Edição em Lote:").pack(side=tk.LEFT)
        self.entry_batch = ttk.Entry(frame, width=15); self.entry_batch.pack(side=tk.LEFT, padx=5)
        ttk.Button(frame, text="Aplicar Selecionados", command=self.apply_batch).pack(side=tk.LEFT)
        ttk.Button(frame, text="🔁 Aplicar em Múltiplos Setups", command=self.open_multi_setup_dialog).pack(side=tk.LEFT, padx=10)
        btn_save = ttk.Button(frame, text="💾 SALVAR ALTERAÇÕES DO SETUP", command=self.save_current_setup)
        btn_save.pack(side=tk.RIGHT, padx=10)

    # ---------- Clipboard ----------

    def copy_setup_name(self, event=None):
        sel = self.cb_setups.get()
        if sel:
            self.copy_to_clipboard(sel)
        return "break"

    def copy_var_info(self, event=None):
        sel = self.tree_vars.selection()
        if not sel:
            return "break"
        vid = sel[0]
        vals = self.tree_vars.item(vid, "values")
        if len(vals) >= 6:
            text = f"{vals[0]}\t{vals[1]}\t{vals[5]}"
            self.copy_to_clipboard(text)
        return "break"

    # ---------- Carregamento da pasta System ----------

    def select_system_folder(self):
        path = filedialog.askdirectory(title="Selecione a pasta 'System' do Promob")
        if not path:
            return
        atributos_path = os.path.join(path, "Atributos")
        config_path = os.path.join(path, "Config", "Attributes")
        if not os.path.exists(atributos_path) or not os.path.exists(config_path):
            messagebox.showerror("Erro", "Estrutura inválida. Necessário 'Atributos' e 'Config/Attributes'.")
            return
        self.system_path = path
        self.atributos_path = atributos_path
        self.config_path = config_path
        self.lbl_status_folder.config(text=path, foreground="blue")
        try:
            path_sugestao = os.path.join(atributos_path, "sugestaoctrl.attributes")
            path_property = os.path.join(atributos_path, "property.category")
            if not os.path.exists(path_property):
                path_property = os.path.join(atributos_path, "property.xml")
            self.property_path = path_property
            self.parse_sugestao(path_sugestao)
            self.parse_property(path_property)
            path_index = os.path.join(config_path, "index.definitions")
            self.load_index_definitions(path_index)
        except Exception as e:
            messagebox.showerror("Erro ao carregar arquivos base", str(e))
            self.lbl_status_folder.config(text="Erro no carregamento", foreground="red")

    def load_index_definitions(self, filepath):
        self.index_path = filepath
        self.available_setups = {}
        self.cb_setups["values"] = []
        self.safe_set_cb_setups("")
        if not os.path.exists(filepath):
            messagebox.showerror("Erro", "Arquivo index.definitions não encontrado.")
            return
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            combo_items = []
            for defi in root.findall("DEFINITION"):
                sid = defi.get("ID")
                desc = defi.get("DESCRIPTION")
                file_ref = defi.get("FILE")
                self.available_setups[sid] = {"description": desc, "file_ref": file_ref}
                combo_items.append(f"{sid} - {desc}")
            self.cb_setups["values"] = combo_items
            messagebox.showinfo("Sucesso", f"Sistema carregado!\n{len(combo_items)} setups encontrados.")
        except Exception as e:
            messagebox.showerror("Erro ao ler index", str(e))

    def on_setup_change(self, event):
        selection = self.cb_setups.get()
        if not selection:
            return
        sid = selection.split(" - ")[0]
        self.current_setup_id = sid
        self.last_setup_text = selection
        target_file = os.path.join(self.config_path, f"{sid}.attributes")
        if not os.path.exists(target_file):
            messagebox.showwarning("Aviso", f"Arquivo não encontrado:\n{target_file}")
            return
        self.load_setup_values(target_file)

    def load_setup_values(self, filepath):
        self.db_values = {}
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            for attr in root.findall("ATTRIBUTE"):
                self.db_values[attr.get("ID")] = attr.get("VALUE")
            self.refresh_table()
        except Exception as e:
            messagebox.showerror("Erro ao ler setup", str(e))

    # ---------- CRUD de setups ----------

    def duplicate_setup_dialog(self):
        if not self.system_path:
            messagebox.showwarning("Aviso", "Selecione a pasta System primeiro.")
            return
        new_id = simpledialog.askstring("Novo Setup", "Digite o ID do novo setup (Números):")
        if not new_id or new_id in self.available_setups:
            if new_id:
                messagebox.showerror("Erro", "ID inválido ou já existente.")
            return
        new_desc = simpledialog.askstring("Novo Setup", "Digite o Nome/Descrição:")
        if not new_desc:
            return
        base_file = None
        if self.current_setup_id and messagebox.askyesno("Copiar Base", f"Copiar dados de ({self.current_setup_id})?"):
            base_file = os.path.join(self.config_path, f"{self.current_setup_id}.attributes")
        new_filename = f"{new_id}.attributes"
        new_filepath = os.path.join(self.config_path, new_filename)
        try:
            if base_file and os.path.exists(base_file):
                shutil.copy2(base_file, new_filepath)
            else:
                root = ET.Element("ATTRIBUTES")
                root.set("DESCRIPTION", new_desc)
                ET.ElementTree(root).write(new_filepath)
            self.append_to_index(new_id, new_desc, new_filename)
            self.load_index_definitions(self.index_path)
            self.safe_set_cb_setups(f"{new_id} - {new_desc}")
            self.current_setup_id = new_id
            self.on_setup_change(None)
        except Exception as e:
            messagebox.showerror("Erro ao criar setup", str(e))

    def rename_setup_dialog(self):
        if not self.current_setup_id or not self.index_path:
            messagebox.showwarning("Aviso", "Nenhum setup selecionado.")
            return
        sid = self.current_setup_id
        new_desc = simpledialog.askstring("Renomear Setup", "Novo Nome/Descrição para o setup:")
        if not new_desc:
            return
        self.rename_setup(sid, new_desc, show_success=True)

    def rename_setup(self, sid, new_desc, show_success=False):
        """Renomeia o setup no index.definitions e recarrega a lista."""
        try:
            tree = ET.parse(self.index_path)
            root = tree.getroot()
            found = False
            for defi in root.findall("DEFINITION"):
                if defi.get("ID") == sid:
                    defi.set("DESCRIPTION", new_desc)
                    found = True
                    break
            if not found:
                messagebox.showerror("Erro", "Setup não encontrado no index.definitions.")
                return False
            tree.write(self.index_path)
            self.load_index_definitions(self.index_path)
            self.safe_set_cb_setups(f"{sid} - {new_desc}")
            self.current_setup_id = sid
            if show_success:
                messagebox.showinfo("Sucesso", f"Setup {sid} renomeado para: {new_desc}")
            return True
        except Exception as e:
            messagebox.showerror("Erro ao renomear", str(e))
            return False

    def delete_setup(self):
        if not self.current_setup_id or not self.config_path or not self.index_path:
            messagebox.showwarning("Aviso", "Nenhum setup selecionado.")
            return
        sid = self.current_setup_id
        if not messagebox.askyesno("Confirmação", f"Deletar setup {sid}? Isso removerá do index.definitions."):
            return
        setup_file = os.path.join(self.config_path, f"{sid}.attributes")

        try:
            if os.path.exists(setup_file):
                os.remove(setup_file)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível remover o arquivo do setup: {e}")
            return

        try:
            tree = ET.parse(self.index_path)
            root = tree.getroot()
            removed = False
            for defi in list(root.findall("DEFINITION")):
                if defi.get("ID") == sid:
                    root.remove(defi)
                    removed = True
            if not removed:
                messagebox.showwarning("Aviso", "Setup não estava no index.definitions.")
            tree.write(self.index_path)
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao atualizar index.definitions: {e}")
            return

        self.current_setup_id = None
        self.db_values = {}
        self.refresh_table()
        self.load_index_definitions(self.index_path)
        self.safe_set_cb_setups("")
        messagebox.showinfo("Sucesso", f"Setup {sid} deletado.")

    def append_to_index(self, sid, desc, filename):
        try:
            tree = ET.parse(self.index_path)
            root = tree.getroot()
            file_str = f"%PastaSistema%\\Config\\Attributes\\{filename}"
            elem = ET.SubElement(root, "DEFINITION")
            elem.set("ID", str(sid))
            elem.set("DESCRIPTION", desc)
            elem.set("FILE", file_str)
            tree.write(self.index_path)
        except Exception as e:
            raise Exception(f"Falha ao atualizar index: {e}")

    # ---------- Categorias / imagens ----------

    IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif")
    POPUP_MAX_SIZE = (1200, 850)

    def expand_image_path(self, raw):
        """Limpa o caminho vindo do property e resolve variáveis do Promob
        (%PastaSistema%, {PastaSistema}...) e do Windows (%APPDATA%...)."""
        rel = raw.strip().strip('"').strip("'").strip()
        if not rel:
            return ""
        if self.system_path:
            for token in ("%PastaSistema%", "{PastaSistema}", "%SystemFolder%", "%SYSTEM%"):
                idx = rel.lower().find(token.lower())
                if idx != -1:
                    rel = rel[:idx] + self.system_path + rel[idx + len(token):]
        rel = os.path.expandvars(rel)
        rel = rel.replace("/", os.sep).replace("\\", os.sep)
        return rel

    def build_image_index(self):
        """Indexa por nome de arquivo (minúsculo) todas as imagens da pasta System.
        Usado como último recurso quando o caminho do property não bate."""
        index = {}
        if self.system_path and os.path.isdir(self.system_path):
            for dirpath, _dirnames, filenames in os.walk(self.system_path):
                for fn in filenames:
                    if fn.lower().endswith(self.IMAGE_EXTS):
                        index.setdefault(fn.lower(), os.path.join(dirpath, fn))
        self.image_file_index = index
        return index

    def image_candidates(self, rel_clean):
        candidates = []
        if os.path.isabs(rel_clean):
            candidates.append(rel_clean)
        else:
            bases = []
            if self.property_path:
                bases.append(os.path.dirname(self.property_path))
            if self.atributos_path:
                bases.append(self.atributos_path)
                bases.append(os.path.join(self.atributos_path, "imagens"))
                bases.append(os.path.join(self.atributos_path, "Imagens"))
            if self.system_path:
                bases.append(self.system_path)
                bases.append(os.path.dirname(self.system_path))
                bases.append(os.path.join(self.system_path, "Atributos", "imagens"))
                bases.append(os.path.join(self.system_path, "Imagens"))
            for b in bases:
                candidates.append(os.path.join(b, rel_clean))

        # Caminho sem extensão: testa as extensões comuns
        if not os.path.splitext(rel_clean)[1]:
            candidates = [c + ext for c in candidates for ext in self.IMAGE_EXTS]

        # Último recurso: procura o arquivo pelo nome em qualquer subpasta da System
        index = self.image_file_index if self.image_file_index is not None else self.build_image_index()
        name = os.path.basename(rel_clean).lower()
        names = [name] if os.path.splitext(name)[1] else [name + ext for ext in self.IMAGE_EXTS]
        for n in names:
            if n in index:
                candidates.append(index[n])
        return candidates

    def open_photo(self, p, full):
        if PIL_AVAILABLE:
            with Image.open(p) as src:
                src.load()
                img = src.copy()
            # JPG em CMYK, PNG paletizado, 16 bits etc. não são aceitos direto pelo Tk
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
            if full:
                img.thumbnail(self.POPUP_MAX_SIZE, Image.Resampling.LANCZOS)
            else:
                img.thumbnail((16, 16), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img, master=self.root)
        if not p.lower().endswith((".png", ".gif")):
            raise ValueError("formato exige Pillow (python -m pip install pillow)")
        return tk.PhotoImage(file=p, master=self.root)

    def load_cat_image(self, img_rel_path, full=False):
        """Carrega e cacheia a imagem de categoria (apenas folhas). full=True retorna imagem grande.
        Em caso de falha, self.last_image_error guarda os caminhos testados e o erro."""
        self.last_image_error = ""
        if not img_rel_path:
            return None

        rel_clean = self.expand_image_path(img_rel_path)
        if not rel_clean:
            return None

        cache = self.full_image_cache if full else self.image_cache
        seen = []
        errors = []
        for path in self.image_candidates(rel_clean):
            p = os.path.normpath(path)
            if p in seen:
                continue
            seen.append(p)
            if not os.path.isfile(p):
                continue
            if p in cache:
                return cache[p]
            try:
                photo = self.open_photo(p, full)
                cache[p] = photo
                return photo
            except Exception as e:
                errors.append(f"{p}: {type(e).__name__}: {e}")

        lines = [f"Caminho no property: {img_rel_path}"]
        if errors:
            lines.append("\nArquivo encontrado, mas falhou ao abrir:")
            lines.extend(errors)
        else:
            lines.append("\nArquivo não encontrado. Caminhos testados:")
            lines.extend(seen[:12])
            if len(seen) > 12:
                lines.append(f"... e mais {len(seen) - 12}")
        self.last_image_error = "\n".join(lines)
        return None

    def parse_property(self, filepath):
        self.property_path = filepath
        for i in self.tree_cats.get_children():
            self.tree_cats.delete(i)
        self.cat_names = {}
        self.cat_images = {}
        self.cat_img_attrs = {}
        self.image_cache = {}
        self.full_image_cache = {}
        self.image_file_index = None

        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            main_node = self.tree_cats.insert("", "end", iid="__ALL__", text="Main", values=("__ALL__",), open=True)

            def has_subcategories(cat_elem):
                sub = cat_elem.find("CATEGORYCOLLECTION")
                if sub is None:
                    return False
                for c in sub:
                    if c.tag == "CATEGORY":
                        return True
                return False

            # O mesmo CATEGORY ID pode aparecer em mais de um ramo do property;
            # a Treeview exige iids únicos, então geramos sufixos __2, __3...
            used_iids = set()

            def make_unique_iid(cat_id):
                if cat_id not in used_iids:
                    used_iids.add(cat_id)
                    return cat_id
                counter = 2
                candidate = f"{cat_id}__{counter}"
                while candidate in used_iids:
                    counter += 1
                    candidate = f"{cat_id}__{counter}"
                used_iids.add(candidate)
                return candidate

            def add_nodes(element, parent_node="__ALL__"):
                for child in element:
                    if child.tag == "CATEGORY":
                        cat_id = str(child.get("ID"))
                        cat_name = child.get("DESCRIPTION", child.get("NAME", cat_id))

                        self.cat_names[cat_id] = cat_name

                        node_iid = make_unique_iid(cat_id)

                        leaf = not has_subcategories(child)
                        img_attr = (child.get("IMAGE") or child.get("ICON") or "").strip()
                        if img_attr:
                            self.cat_img_attrs[node_iid] = img_attr
                        img_obj = self.load_cat_image(img_attr) if leaf and img_attr else None
                        if img_obj:
                            self.cat_images[cat_id] = img_obj

                        kwargs = {
                            "parent": parent_node,
                            "index": "end",
                            "iid": node_iid,
                            "text": cat_name,
                            "values": (cat_id,),
                        }
                        if img_obj:
                            kwargs["image"] = img_obj

                        node_id = self.tree_cats.insert(**kwargs)

                        sub = child.find("CATEGORYCOLLECTION")
                        if sub is not None:
                            add_nodes(sub, node_id)
                        else:
                            add_nodes(child, node_id)
                    elif child.tag == "CATEGORYCOLLECTION":
                        add_nodes(child, parent_node)

            add_nodes(root, main_node)

            if not PIL_AVAILABLE:
                messagebox.showwarning(
                    "Imagens",
                    "Para exibir JPG nas categorias ou no popup, instale o Pillow:\n\npython -m pip install pillow",
                )
        except Exception as e:
            messagebox.showerror("Erro Property", str(e))

    def parse_sugestao(self, filepath):
        self.db_vars = {}
        self.map_cat_vars = {}
        self.map_path_vars = {}
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            col = root.find("ATTRIBUTEDEFINITIONCOLLECTION")
            if col is None:
                col = root
            for attr in col.findall("ATTRIBUTEDEFINITION"):
                vid = attr.get("ID")
                cid = attr.get("WIZARDCATEGORYID")
                cat_path = (attr.get("CATEGORY") or "").strip()
                if cat_path:
                    self.map_path_vars.setdefault(cat_path, []).append(vid)

                options = []
                pv = attr.find("PROPOSEDVALUES")
                if pv is not None:
                    options = [p.get("VALUE") for p in pv.findall("PROPOSEDVALUE")]
                else:
                    vv = attr.find("VALIDVALUES")
                    if vv is not None:
                        options = [p.get("VALUE") for p in vv.findall("VALIDVALUE")]

                attr_type = (attr.get("TYPE") or "").lower()
                default_val = (attr.get("DEFAULTVALUE") or "").strip().lower()
                is_bool_like = attr_type in ("bool", "boolean") or default_val in ("true", "false")
                only_proposed = (attr.get("ONLYPROPOSEDVALUES") or "").upper() == "Y"
                if not options and is_bool_like:
                    options = ["True", "False"]

                self.db_vars[vid] = {
                    "name": attr.get("NAME", ""),
                    "desc": attr.get("DESCRIPTION", ""),
                    "default": attr.get("DEFAULTVALUE", ""),
                    "cat_link": cid,
                    "cat_path": cat_path,
                    "options": options,
                    "type": attr_type,
                    "only_proposed": only_proposed,
                }
                if not cid:
                    continue
                cid_str = str(cid)
                self.map_cat_vars.setdefault(cid_str, []).append(vid)
        except Exception as e:
            messagebox.showerror("Erro Sugestao", str(e))

    # ---------- Filtros ----------

    def on_category_select(self, event):
        sel = self.tree_cats.selection()
        if not sel:
            return
        self.on_advanced_search(None)

    def split_terms(self, s: str):
        if "+" in s:
            return [p.strip() for p in s.split("+") if p.strip()]
        return [s] if s else []

    def match_terms(self, haystack: str, terms):
        return all(t in haystack for t in terms)

    def get_real_cat_id(self, tree_iid):
        """Converte o iid (único na Treeview) de volta para o CATEGORY ID real,
que é o que está gravado em values e é usado por map_cat_vars/cat_names."""
        try:
            vals = self.tree_cats.item(tree_iid, "values")
        except tk.TclError:
            return tree_iid
        return vals[0] if vals else tree_iid

    def get_all_vars_in_branch(self, tree_item_id):
        if tree_item_id == "__ALL__":
            return list(self.db_vars.keys())
        ids = []
        real_cat_id = self.get_real_cat_id(tree_item_id)
        if real_cat_id in self.map_cat_vars:
            ids.extend(self.map_cat_vars.get(real_cat_id, []))
        for child_item in self.tree_cats.get_children(tree_item_id):
            ids.extend(self.get_all_vars_in_branch(child_item))
        return ids

    def clear_filters(self):
        self.ent_f_id.delete(0, tk.END)
        self.ent_f_name.delete(0, tk.END)
        self.ent_f_cat.delete(0, tk.END)
        self.ent_f_val.delete(0, tk.END)
        self.ent_f_desc.delete(0, tk.END)
        self.on_advanced_search(None)

    def on_advanced_search(self, event):
        sel = self.tree_cats.selection()
        if not sel:
            return
        f_id_terms = self.split_terms(self.ent_f_id.get().lower())
        f_name_terms = self.split_terms(self.ent_f_name.get().lower())
        f_cat_terms = self.split_terms(self.ent_f_cat.get().lower())
        f_val_terms = self.split_terms(self.ent_f_val.get().lower())
        f_desc_terms = self.split_terms(self.ent_f_desc.get().lower())

        for i in self.tree_vars.get_children():
            self.tree_vars.delete(i)
        ids = list(dict.fromkeys(self.get_all_vars_in_branch(sel[0])))

        for vid in ids:
            data = self.db_vars.get(vid, {})
            val_atual = self.db_values.get(vid, data.get("default", "")).lower()
            cat_link = str(data.get("cat_link", "") or "")
            cat_path = data.get("cat_path", "")
            cat_nome = (cat_path or self.cat_names.get(cat_link, "")).lower()
            nome_var = data.get("name", "").lower()
            desc_var = data.get("desc", "").lower()
            id_var = vid.lower()

            if f_id_terms and not self.match_terms(id_var, f_id_terms): continue
            if f_name_terms and not self.match_terms(nome_var, f_name_terms): continue
            if f_cat_terms and not self.match_terms(cat_nome, f_cat_terms): continue
            if f_val_terms and not self.match_terms(val_atual, f_val_terms): continue
            if f_desc_terms and not self.match_terms(desc_var, f_desc_terms): continue

            self.insert_row(vid)

    def insert_row(self, vid, score_val=""):
        d = self.db_vars.get(vid, {})
        val = self.db_values.get(vid, d.get("default", ""))
        cat_id_link = str(d.get("cat_link", "") or "")
        cat_path = d.get("cat_path", "")
        cat_display = cat_path if cat_path else self.cat_names.get(cat_id_link, cat_id_link)
        self.tree_vars.insert("", "end", iid=vid,
                              values=(vid, d.get("name"), cat_display, val, d.get("default"), d.get("desc"), score_val))

    # ---------- Edição inline ----------

    def get_cell_bbox(self, vid):
        bbox = self.tree_vars.bbox(vid, "Valor Atual")
        if not bbox:
            bbox = self.tree_vars.bbox(vid, "#4")
        return bbox

    def destroy_inline_editor(self):
        if self.inline_editor is not None and self.inline_editor.winfo_exists():
            self.inline_editor.destroy()
        self.inline_editor = None

    def show_inline_combobox(self, vid, options):
        self.destroy_inline_editor()
        bbox = self.get_cell_bbox(vid)
        if not bbox: return
        x, y, w, h = bbox
        curr = self.tree_vars.item(vid, "values")[3]
        cb = ttk.Combobox(self.tree_vars, values=options, state="readonly")
        cb.place(x=x, y=y, width=w, height=h)
        cb.set(curr)
        cb.selection_range(0, tk.END)
        cb.focus_set()

        def commit_and(option_val, move_next=False, move_prev=False):
            self.db_values[vid] = option_val
            self.update_row_visual(vid)
            self.destroy_inline_editor()
            if move_next:
                self.edit_next_row(vid)
            elif move_prev:
                self.edit_prev_row(vid)

        def move(delta):
            if not options: return "break"
            try:
                idx = options.index(cb.get())
            except ValueError:
                idx = 0
            new_idx = (idx + delta) % len(options)
            cb.set(options[new_idx])
            cb.selection_range(0, tk.END)
            return "break"

        cb.bind("<<ComboboxSelected>>", lambda e: commit_and(cb.get(), False, False))
        cb.bind("<Return>", lambda e: commit_and(cb.get(), False, False))
        cb.bind("<FocusOut>", lambda e: commit_and(cb.get(), False, False))
        cb.bind("<Escape>", lambda e: self.destroy_inline_editor())
        cb.bind("<Tab>", lambda e: (commit_and(cb.get(), True, False), "break")[1])
        cb.bind("<Shift-Tab>", lambda e: (commit_and(cb.get(), False, True), "break")[1])
        cb.bind("<ISO_Left_Tab>", lambda e: (commit_and(cb.get(), False, True), "break")[1])
        cb.bind("<Up>", lambda e: move(-1))
        cb.bind("<Down>", lambda e: move(1))

        self.inline_editor = cb

    def show_inline_entry(self, vid):
        self.destroy_inline_editor()
        bbox = self.get_cell_bbox(vid)
        if not bbox: return
        x, y, w, h = bbox
        curr = self.tree_vars.item(vid, "values")[3]
        entry = ttk.Entry(self.tree_vars)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, curr)
        entry.selection_range(0, tk.END)
        entry.focus_set()

        def commit_and(val, move_next=False, move_prev=False):
            self.db_values[vid] = val
            self.update_row_visual(vid)
            self.destroy_inline_editor()
            if move_next:
                self.edit_next_row(vid)
            elif move_prev:
                self.edit_prev_row(vid)

        entry.bind("<Return>", lambda e: commit_and(entry.get(), False, False))
        entry.bind("<FocusOut>", lambda e: commit_and(entry.get(), False, False))
        entry.bind("<Escape>", lambda e: self.destroy_inline_editor())
        entry.bind("<Tab>", lambda e: (commit_and(entry.get(), True, False), "break")[1])
        entry.bind("<Shift-Tab>", lambda e: (commit_and(entry.get(), False, True), "break")[1])
        entry.bind("<ISO_Left_Tab>", lambda e: (commit_and(entry.get(), False, True), "break")[1])

        self.inline_editor = entry

    def edit_next_row(self, current_vid):
        children = list(self.tree_vars.get_children())
        if not children:
            return
        try:
            idx = children.index(current_vid)
        except ValueError:
            idx = -1
        if idx < len(children) - 1:
            next_vid = children[idx + 1]
            self.tree_vars.selection_set(next_vid)
            self.tree_vars.focus(next_vid)
            self.start_inline_edit(next_vid)

    def edit_prev_row(self, current_vid):
        children = list(self.tree_vars.get_children())
        if not children:
            return
        try:
            idx = children.index(current_vid)
        except ValueError:
            idx = 0
        if idx > 0:
            prev_vid = children[idx - 1]
            self.tree_vars.selection_set(prev_vid)
            self.tree_vars.focus(prev_vid)
            self.start_inline_edit(prev_vid)

    def on_tab_edit_next(self, event):
        if self.inline_editor is not None and self.inline_editor.winfo_exists():
            return "break"
        sel = self.tree_vars.selection()
        if not sel:
            return "break"
        current_vid = sel[0]
        self.edit_next_row(current_vid)
        return "break"

    def on_shift_tab_edit_prev(self, event):
        if self.inline_editor is not None and self.inline_editor.winfo_exists():
            return "break"
        sel = self.tree_vars.selection()
        if not sel:
            return "break"
        current_vid = sel[0]
        self.edit_prev_row(current_vid)
        return "break"

    def start_inline_edit(self, vid):
        d = self.db_vars.get(vid, {})
        opts = d.get("options", []) or []
        attr_type = d.get("type", "")
        only_prop = d.get("only_proposed", False)
        current_val = str(self.db_values.get(vid, d.get("default", ""))).strip().lower()
        is_bool_like = attr_type in ("bool", "boolean") or current_val in ("true", "false")
        if not opts and is_bool_like:
            opts = ["True", "False"]
        if only_prop and opts:
            self.show_inline_combobox(vid, opts)
        else:
            self.show_inline_entry(vid)

    def on_double_click_var(self, event):
        sel = self.tree_vars.selection()
        if not sel:
            return
        vid = sel[0]
        self.start_inline_edit(vid)

    def apply_batch(self):
        sel = self.tree_vars.selection()
        v = self.entry_batch.get()
        for vid in sel:
            self.db_values[vid] = v
            self.update_row_visual(vid)

    def update_row_visual(self, vid):
        if self.tree_vars.exists(vid):
            d = self.db_vars.get(vid, {})
            old = self.tree_vars.item(vid, "values")
            self.tree_vars.item(
                vid, values=(vid, d.get("name"), old[2], self.db_values[vid], d.get("default"), d.get("desc"), old[6]))

    def refresh_table(self):
        sel = self.tree_cats.selection()
        if sel:
            self.on_advanced_search(None)

    # ---------- Agente de busca global ----------

    def normalize_text(self, text):
        if not text:
            return ""
        text = str(text)
        return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower()

    def run_agent_search(self, event=None):
        query = self.entry_agent.get()
        if not query:
            return
        for i in self.tree_vars.get_children():
            self.tree_vars.delete(i)
        stopwords = ["de", "da", "do", "as", "os", "em", "na", "no", "para", "com", "que", "o", "a", "as",
                     "um", "uma", "me", "mostre", "todas", "configuracoes"]
        norm_q = self.normalize_text(query)
        keywords = [w for w in norm_q.split() if w not in stopwords and len(w) > 2]
        if not keywords:
            return
        results = []
        for vid, data in self.db_vars.items():
            score = 0
            v_name = self.normalize_text(data["name"])
            v_desc = self.normalize_text(data["desc"])
            cat_name = self.normalize_text(self.cat_names.get(str(data.get("cat_link", "") or ""), ""))
            for k in keywords:
                if k in cat_name: score += 3
                if k in v_name: score += 2
                if k in v_desc: score += 1
            if score > 0:
                results.append((score, vid))
        results.sort(key=lambda x: x[0], reverse=True)
        for score, vid in results:
            self.insert_row(vid, score)
        self.root.title(f"Agente: {len(results)} resultados")

    # ---------- Gravação ----------

    def save_current_setup(self):
        if not self.current_setup_id or not self.config_path:
            messagebox.showwarning("Erro", "Nenhum setup carregado.")
            return
        file_name = f"{self.current_setup_id}.attributes"
        full_path = os.path.join(self.config_path, file_name)
        try:
            root = ET.Element("ATTRIBUTES")
            desc = self.available_setups.get(self.current_setup_id, {}).get("description", "Setup Editado")
            root.set("DESCRIPTION", desc)
            for k, v in self.db_values.items():
                ET.SubElement(root, "ATTRIBUTE", ID=k, VALUE=str(v))
            tree = ET.ElementTree(root)
            tree.write(full_path)
            messagebox.showinfo("Sucesso", f"Setup {self.current_setup_id} salvo com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))

    # ---------- Aplicação em múltiplos setups ----------

    def apply_value_to_multiple_setups(self, var_ids, new_value, setup_ids):
        """Grava `new_value` SOMENTE nas variáveis de `var_ids`, dentro dos
arquivos .attributes dos `setup_ids` informados. Todo o resto de cada
arquivo (variáveis não selecionadas) permanece intocado — diferente de
save_current_setup(), que reescreve o setup inteiro a partir do estado
em memória."""
        updated = 0
        errors = []
        for sid in setup_ids:
            file_path = os.path.join(self.config_path, f"{sid}.attributes")
            if not os.path.exists(file_path):
                errors.append(f"{sid}: arquivo não encontrado ({file_path})")
                continue
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
                existing = {attr.get("ID"): attr for attr in root.findall("ATTRIBUTE")}
                for vid in var_ids:
                    if vid in existing:
                        existing[vid].set("VALUE", str(new_value))
                    else:
                        ET.SubElement(root, "ATTRIBUTE", ID=vid, VALUE=str(new_value))
                tree.write(file_path)
                updated += 1

                # Mantém a tela coerente se o setup ativo foi um dos alterados
                if sid == self.current_setup_id:
                    for vid in var_ids:
                        self.db_values[vid] = new_value
                        self.update_row_visual(vid)
            except Exception as e:
                errors.append(f"{sid}: {e}")
        return updated, errors

    def open_multi_setup_dialog(self):
        sel = self.tree_vars.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione ao menos uma variável na tabela antes.")
            return
        if not self.config_path or not self.available_setups:
            messagebox.showwarning("Aviso", "Nenhum setup carregado. Selecione a pasta System primeiro.")
            return

        var_ids = list(sel)

        top = tk.Toplevel(self.root)
        top.title(f"Aplicar valor em múltiplos setups ({len(var_ids)} variável(is))")
        top.geometry("480x560")
        top.transient(self.root)
        top.grab_set()

        names = [self.db_vars.get(v, {}).get("name", v) for v in var_ids]
        resumo = ", ".join(names[:5]) + (f" e mais {len(names) - 5}..." if len(names) > 5 else "")
        ttk.Label(
            top, text=f"Variáveis selecionadas ({len(var_ids)}):\n{resumo}",
            wraplength=440, justify="left",
        ).pack(padx=10, pady=(10, 5), anchor="w")

        fr_val = ttk.Frame(top)
        fr_val.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(fr_val, text="Novo valor:").pack(side=tk.LEFT)
        ent_val = ttk.Entry(fr_val)
        ent_val.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        prefill = self.entry_batch.get().strip() or str(self.db_values.get(var_ids[0], ""))
        ent_val.insert(0, prefill)
        ent_val.focus_set()

        ttk.Label(top, text="Selecione os setups (engenharias) para aplicar:").pack(padx=10, pady=(10, 0), anchor="w")

        fr_btns_sel = ttk.Frame(top)
        fr_btns_sel.pack(fill=tk.X, padx=10, pady=5)

        fr_list_container = ttk.Frame(top, relief=tk.SUNKEN, borderwidth=1)
        fr_list_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(fr_list_container, highlightthickness=0)
        scroll = ttk.Scrollbar(fr_list_container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        check_vars = {}
        for sid, info in sorted(self.available_setups.items(), key=lambda kv: kv[0]):
            var = tk.BooleanVar(value=False)
            check_vars[sid] = var
            label = f"{sid} - {info.get('description', '')}"
            cb = ttk.Checkbutton(inner, text=label, variable=var)
            cb.pack(anchor="w", padx=5, pady=2, fill=tk.X)
            cb.bind("<MouseWheel>", _on_mousewheel)

        def select_all():
            for v in check_vars.values():
                v.set(True)

        def deselect_all():
            for v in check_vars.values():
                v.set(False)

        ttk.Button(fr_btns_sel, text="✅ Selecionar Todos", command=select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(fr_btns_sel, text="❌ Desmarcar Todos", command=deselect_all).pack(side=tk.LEFT, padx=5)

        fr_actions = ttk.Frame(top)
        fr_actions.pack(fill=tk.X, padx=10, pady=10)

        def do_apply():
            new_value = ent_val.get()
            chosen = [sid for sid, v in check_vars.items() if v.get()]
            if not chosen:
                messagebox.showwarning("Aviso", "Selecione ao menos um setup.", parent=top)
                return
            if not messagebox.askyesno(
                "Confirmar",
                f"Aplicar o valor '{new_value}' em {len(var_ids)} variável(is),\n"
                f"em {len(chosen)} setup(s) selecionado(s)?\n\n"
                "Isso grava diretamente nos arquivos .attributes desses setups\n"
                "(as demais variáveis de cada arquivo não são alteradas).",
                parent=top,
            ):
                return
            updated, errors = self.apply_value_to_multiple_setups(var_ids, new_value, chosen)
            msg = f"{updated} de {len(chosen)} setup(s) atualizado(s) com sucesso."
            if errors:
                msg += "\n\nErros:\n" + "\n".join(errors)
                messagebox.showwarning("Concluído com avisos", msg, parent=top)
            else:
                messagebox.showinfo("Sucesso", msg, parent=top)
            top.destroy()

        ttk.Button(fr_actions, text="Aplicar", command=do_apply).pack(side=tk.RIGHT, padx=5)
        ttk.Button(fr_actions, text="Cancelar", command=top.destroy).pack(side=tk.RIGHT, padx=5)

    # ---------- Renomear setup direto no combobox ----------

    def on_setup_edit_finish(self, event=None):
        if self.suppress_setup_edit:
            return
        if not self.current_setup_id or not self.index_path:
            return
        current_text = self.cb_setups.get().strip()
        if not current_text:
            return
        if current_text == self.last_setup_text:
            return

        sid = self.current_setup_id
        expected_prefix = f"{sid} - "
        if current_text.startswith(expected_prefix):
            new_desc = current_text[len(expected_prefix):].strip()
        else:
            new_desc = current_text

        if not new_desc:
            messagebox.showwarning("Aviso", "O nome do setup não pode ficar vazio.")
            self.safe_set_cb_setups(self.last_setup_text)
            return

        if not messagebox.askyesno("Confirmar", f"Confirmar mudança do setup {sid} para:\n{new_desc}?"):
            self.safe_set_cb_setups(self.last_setup_text)
            return

        if self.rename_setup(sid, new_desc, show_success=True):
            self.last_setup_text = f"{sid} - {new_desc}"
        else:
            self.safe_set_cb_setups(self.last_setup_text)

    def safe_set_cb_setups(self, value):
        self.suppress_setup_edit = True
        try:
            self.cb_setups.set(value)
            self.last_setup_text = value
        finally:
            self.root.after(50, lambda: setattr(self, "suppress_setup_edit", False))

    # ---------- Popup de imagem ----------

    def show_selected_category_image(self):
        sel = self.tree_cats.selection()
        if not sel:
            messagebox.showinfo("Imagem", "Selecione uma categoria.")
            return
        cid = sel[0]
        if cid == "__ALL__":
            messagebox.showinfo("Imagem", "Selecione uma categoria folha.")
            return

        # cat_img_attrs é indexado pelo iid da Treeview (único por nó),
        # então funciona mesmo quando o CATEGORY ID se repete em ramos diferentes
        img_attr = self.cat_img_attrs.get(cid, "")

        if not img_attr:
            messagebox.showinfo("Imagem", "Categoria sem imagem.")
            return

        img = self.load_cat_image(img_attr, full=True)
        if not img:
            detalhe = self.last_image_error or "Sem detalhes."
            if not PIL_AVAILABLE:
                detalhe += "\n\nPillow não está instalado (JPG/BMP não abrem):\npython -m pip install pillow"
            messagebox.showerror("Imagem", "Não foi possível carregar a imagem.\n\n" + detalhe)
            return

        real_cat_id = self.get_real_cat_id(cid)
        top = tk.Toplevel(self.root)
        top.title(f"Imagem - {self.cat_names.get(real_cat_id, real_cat_id)}")
        lbl = ttk.Label(top, image=img)
        lbl.image = img
        lbl.pack(padx=10, pady=10)
        ttk.Button(top, text="Fechar", command=top.destroy).pack(pady=5)


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = PromobSetupManager(root)
        root.mainloop()
    except Exception as e:
        with open("log_erro_execucao.txt", "w") as f:
            f.write(traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Erro fatal: {e}", "Erro", 16)
        except Exception:
            pass
