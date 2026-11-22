//! Hace un disco DashFS de prueba para el handler del Amiga (docs/HANDLER_LOOP.md de Dash, fase 2), y escribe lo
//! que el handler debe ver en un manifiesto de texto.
//!
//!     hacer_disco disco.img manifiesto.txt [MB]
//!
//! El disco: ficheros con eñes y tildes, uno pequeño (datos en el nodo), uno grande que LZ4 comprime y otro que no,
//! un cajón con subcajones, comentarios y bits del Amiga, una carpeta con 300 ficheros (H-tree de más de un nivel),
//! un cajón que distingue mayúsculas, una instantánea "antes" (luego se cambia un fichero y se borra otro) y un
//! segundo volumen "Otro". Las fechas son fijas: el disco sale igual cada vez salvo su uuid.
use std::fmt::Write as _;
use std::{env, fs, process};

use redoxfs::{AmigaBits, DiskFile, FileSystem, Node, TreePtr};

const T0: u64 = 1_763_812_800; // 2025-11-22 12:00:00 UTC

/// Lo que escribe el manifiesto de cada fichero: su suma (la del handler: suma de bytes por su posición, módulo 2^32)
fn suma(data: &[u8]) -> u32 {
    let mut s: u32 = 0;
    for (i, b) in data.iter().enumerate() {
        s = s.wrapping_add((*b as u32).wrapping_mul((i as u32 % 251) + 1));
    }
    s
}

struct Disco {
    fs: FileSystem<DiskFile>,
    manifiesto: String,
}

impl Disco {
    fn fichero(&mut self, padre: TreePtr<Node>, ruta: &str, nombre: &str, data: &[u8], t: u64) -> TreePtr<Node> {
        let ptr = self
            .fs
            .tx(|tx| {
                let n = tx.create_node(padre, nombre, Node::MODE_FILE | 0o644, t, 0)?;
                if !data.is_empty() {
                    tx.write_node(n.ptr(), 0, data, t, 0)?;
                }
                Ok(n.ptr())
            })
            .expect("crear fichero");
        writeln!(self.manifiesto, "F {}{} {} {}", ruta, nombre, data.len(), suma(data)).unwrap();
        ptr
    }

    fn cajon(&mut self, padre: TreePtr<Node>, ruta: &str, nombre: &str, t: u64) -> TreePtr<Node> {
        let ptr = self
            .fs
            .tx(|tx| Ok(tx.create_node(padre, nombre, Node::MODE_DIR | 0o755, t, 0)?.ptr()))
            .expect("crear cajón");
        writeln!(self.manifiesto, "D {}{}", ruta, nombre).unwrap();
        ptr
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("uso: hacer_disco disco.img manifiesto.txt [MB]");
        process::exit(2);
    }
    let mb: u64 = args.get(3).map(|s| s.parse().expect("MB")).unwrap_or(16);
    let _ = fs::remove_file(&args[1]);
    let disk = DiskFile::create(&args[1], mb * 1024 * 1024).expect("crear la imagen");
    let fs = FileSystem::create(disk, None, T0, 0).expect("crear DashFS");
    let mut d = Disco { fs, manifiesto: String::new() };
    let raiz = TreePtr::<Node>::root();

    d.fichero(raiz, "", "Léeme.txt", "Hola desde DashFS, leído en un Amiga.\n".as_bytes(), T0);
    d.fichero(raiz, "", "corto", b"abc", T0 + 60);
    // grande y comprimible: texto que se repite (LZ4)
    let mut grande = Vec::new();
    for i in 0..30_000 {
        write!(&mut grande as &mut dyn std::io::Write, "línea {:05} del fichero grande\n", i).ok();
    }
    let grande_ptr = d.fichero(raiz, "", "grande.txt", &grande, T0 + 120);
    // que no se comprime: bytes de un generador fijo
    let mut x: u32 = 12345;
    let azar: Vec<u8> = (0..200_000)
        .map(|_| {
            x ^= x << 13;
            x ^= x >> 17;
            x ^= x << 5;
            (x >> 24) as u8
        })
        .collect();
    d.fichero(raiz, "", "azar.bin", &azar, T0 + 180);
    let nota = d.fichero(raiz, "", "con nota", b"tiene comentario y bits\n", T0 + 240);
    d.fs.tx(|tx| {
        tx.set_comment(nota, "Una nota del Amiga con eñe")?;
        tx.set_amiga_bits(nota, AmigaBits::ARCHIVE | AmigaBits::PURE | AmigaBits::SCRIPT)
    })
    .expect("nota");
    writeln!(d.manifiesto, "C con nota|Una nota del Amiga con eñe").unwrap();
    d.fichero(raiz, "", "borrado.txt", b"solo en la instantanea\n", T0 + 300);

    let cajon = d.cajon(raiz, "", "Cajón", T0 + 400);
    d.fichero(cajon, "Cajón/", "dentro.txt", b"un fichero en un cajon\n", T0 + 410);
    let sub = d.cajon(cajon, "Cajón/", "Sub", T0 + 420);
    d.fichero(sub, "Cajón/Sub/", "hondo.txt", b"dos niveles abajo\n", T0 + 430);

    let muchos = d.cajon(raiz, "", "Muchos", T0 + 500);
    for i in 0..300 {
        let nombre = format!("fichero_{:03}_con_un_nombre_largo.txt", i);
        let data = format!("numero {}\n", i);
        d.fichero(muchos, "Muchos/", &nombre, data.as_bytes(), T0 + 500);
    }

    // un cajón que distingue mayúsculas (FS6): "a" y "A" son dos
    let exacto = d.fs.tx(|tx| {
        let n = tx.create_node(raiz, "Exacto", Node::MODE_DIR | 0o755, T0 + 600, 0)?;
        tx.set_casefold(n.ptr(), false)?;
        Ok(n.ptr())
    }).expect("cajón exacto");
    writeln!(d.manifiesto, "D Exacto").unwrap();
    d.fichero(exacto, "Exacto/", "a", b"minuscula\n", T0 + 610);
    d.fichero(exacto, "Exacto/", "A", b"MAYUSCULA\n", T0 + 610);

    // la instantánea, y después un cambio y un borrado que ella no ve
    d.fs.tx(|tx| tx.create_snapshot("antes", T0 + 700, 0)).expect("instantánea");
    writeln!(d.manifiesto, "S antes").unwrap();
    d.fs.tx(|tx| {
        let r = tx.find_node(raiz, "borrado.txt")?;
        tx.remove_node(raiz, "borrado.txt", Node::MODE_FILE).map(|_| r)
    })
    .expect("borrar");
    let nuevo = "Contenido nuevo, despues de la instantanea.\n".as_bytes();
    d.fs.tx(|tx| {
        tx.truncate_node(grande_ptr, 0, T0 + 800, 0)?;
        tx.write_node(grande_ptr, 0, nuevo, T0 + 800, 0)
    })
    .expect("cambiar");
    writeln!(d.manifiesto, "X borrado.txt").unwrap();
    writeln!(d.manifiesto, "N grande.txt {} {}", nuevo.len(), suma(nuevo)).unwrap();

    // otro volumen
    let id = d.fs.tx(|tx| tx.create_volume("Otro", T0 + 900, 0)).expect("volumen");
    d.fs.tx_in(id, |tx| {
        let n = tx.create_node(TreePtr::root(), "del otro.txt", Node::MODE_FILE | 0o644, T0 + 910, 0)?;
        tx.write_node(n.ptr(), 0, b"en el volumen Otro\n", T0 + 910, 0)
    })
    .expect("fichero del otro volumen");
    writeln!(d.manifiesto, "V Otro del otro.txt").unwrap();

    fs::write(&args[2], d.manifiesto).expect("manifiesto");
    println!("hecho: {} ({} MB)", args[1], mb);
}
