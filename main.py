from fastapi import FastAPI, Request, File, UploadFile, Form, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional
import json
import uvicorn
import zipfile
import io
import base64
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader
import tempfile
import os
import requests

app = FastAPI(title="PDF Generator API", version="1.0.0")

# Modello Pydantic opzionale per validare i dati in input
class PDFRequest(BaseModel):
    titolo: Optional[str] = None
    contenuto: Optional[str] = None
    parametri: Optional[Dict[str, Any]] = None

def download_logo() -> Optional[bytes]:
    """
    Scarica il logo da URL e lo restituisce come bytes.
    """
    logo_url = "https://automatikoagency.github.io/dpsonline_genera_pdf/aster_logo.png"
    try:
        print(f"Scaricando logo da: {logo_url}")
        response = requests.get(logo_url, timeout=10)
        response.raise_for_status()
        print(f"Logo scaricato con successo: {len(response.content)} bytes")
        return response.content
    except Exception as e:
        print(f"ERRORE nel download del logo: {e}")
        return None

def create_pdf_from_images(zip_binary_data: bytes) -> bytes:
    """
    Crea un PDF dalle immagini contenute nel file ZIP.
    Ogni immagine diventa una pagina del PDF.
    """
    pdf_buffer = io.BytesIO()

    # Scarica il logo una sola volta
    logo_bytes = download_logo()
    logo_image = None
    if logo_bytes:
        try:
            logo_image = Image.open(io.BytesIO(logo_bytes))
            # Converti in RGB se necessario
            if logo_image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', logo_image.size, (255, 255, 255))
                if logo_image.mode == 'P':
                    logo_image = logo_image.convert('RGBA')
                background.paste(logo_image, mask=logo_image.split()[-1] if logo_image.mode in ('RGBA', 'LA') else None)
                logo_image = background
            elif logo_image.mode != 'RGB':
                logo_image = logo_image.convert('RGB')
            print("Logo preparato con successo")
        except Exception as e:
            print(f"Errore nella preparazione del logo: {e}")
            logo_image = None

    try:
        with zipfile.ZipFile(io.BytesIO(zip_binary_data), 'r') as zip_ref:
            # Crea il PDF
            c = canvas.Canvas(pdf_buffer, pagesize=A4)
            page_width, page_height = A4

            # Lista tutti i file nel ZIP
            file_list = zip_ref.namelist()
            print(f"\nCreazione PDF: trovati {len(file_list)} file nel ZIP")

            # Filtra solo i file immagine (per sicurezza)
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
            image_files = []

            for filename in file_list:
                # Controlla se ha un'estensione di immagine o prova a caricarla
                is_image = any(filename.lower().endswith(ext) for ext in image_extensions)
                if not is_image:
                    # Se non ha estensione, prova comunque a caricarla come immagine
                    try:
                        file_data = zip_ref.read(filename)
                        Image.open(io.BytesIO(file_data))
                        is_image = True
                        print(f"File {filename} riconosciuto come immagine (senza estensione)")
                    except:
                        print(f"File {filename} saltato: non è un'immagine")
                        continue

                if is_image:
                    image_files.append(filename)

            print(f"File immagine trovati: {image_files}")

            if not image_files:
                print("ERRORE: Nessuna immagine trovata nel ZIP!")
                # Crea una pagina vuota con messaggio di errore
                c.drawString(100, 750, "Nessuna immagine trovata nel file ZIP")
                c.showPage()
            else:
                # PRIMA PAGINA: COPERTINA CON LOGO E TITOLO
                print("Creazione pagina di copertina...")

                # Logo centrato
                if logo_image:
                    try:
                        logo_buffer = io.BytesIO()
                        logo_image.save(logo_buffer, format='PNG')
                        logo_buffer.seek(0)

                        # Dimensioni logo copertina (180px)
                        cover_logo_width_px = 180
                        cover_logo_width_pt = cover_logo_width_px * 0.75
                        logo_original_width, logo_original_height = logo_image.size
                        cover_logo_height_pt = (logo_original_height / logo_original_width) * cover_logo_width_pt

                        # Posizione logo centrato al 75% dell'altezza
                        logo_x = (page_width - cover_logo_width_pt) / 2
                        logo_y = page_height * 0.75  # Posiziona il logo al 75% dell'altezza

                        c.drawImage(ImageReader(logo_buffer), logo_x, logo_y, cover_logo_width_pt, cover_logo_height_pt)
                        print(f"Logo copertina aggiunto ({cover_logo_width_pt:.0f}x{cover_logo_height_pt:.0f} pt)")
                    except Exception as e:
                        print(f"Errore logo copertina: {e}")

                # Titolo "SELEZIONE STAMPA" - grande e largo
                margin = 50
                max_text_width = page_width - 2 * margin

                # Calcola dimensione font per "SELEZIONE STAMPA" che occupi quasi tutta la larghezza
                title_text = "SELEZIONE STAMPA"
                font_size = 50  # Inizia con 50pt
                while font_size > 10:
                    title_width = c.stringWidth(title_text, "Helvetica-Bold", font_size)
                    if title_width <= max_text_width:
                        break
                    font_size -= 1

                c.setFont("Helvetica-Bold", font_size)
                title_width = c.stringWidth(title_text, "Helvetica-Bold", font_size)
                title_x = (page_width - title_width) / 2
                title_y = page_height * 0.55  # Molto più vicino al logo (era 0.4)
                c.drawString(title_x, title_y, title_text)

                # Data di oggi - STESSO FONT SIZE del titolo
                today = datetime.now()
                months = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                         "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
                date_text = f"{today.day} {months[today.month-1]} {today.year}"

                # Usa lo STESSO font size del titolo
                c.setFont("Helvetica-Bold", font_size)  # Stesso font_size di "SELEZIONE STAMPA"
                date_width = c.stringWidth(date_text, "Helvetica-Bold", font_size)
                date_x = (page_width - date_width) / 2
                date_y = title_y - 70  # Sotto il titolo (era 80)
                c.drawString(date_x, date_y, date_text)

                print(f"Copertina creata: {title_text} (font {font_size}pt) - {date_text} (font {font_size}pt)")

                # Nuova pagina per le immagini
                c.showPage()

                # Ordina i file per nome (opzionale)
                image_files.sort()

                for i, filename in enumerate(image_files):
                    print(f"Elaborando immagine {i+1}/{len(image_files)}: {filename}")

                    try:
                        # Leggi l'immagine dal ZIP
                        image_data = zip_ref.read(filename)

                        # Apri l'immagine con PIL
                        with Image.open(io.BytesIO(image_data)) as img:
                            # Converti in RGB se necessario (per PNG con trasparenza, ecc.)
                            if img.mode in ('RGBA', 'LA', 'P'):
                                # Crea uno sfondo bianco
                                background = Image.new('RGB', img.size, (255, 255, 255))
                                if img.mode == 'P':
                                    img = img.convert('RGBA')
                                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                                img = background
                            elif img.mode != 'RGB':
                                img = img.convert('RGB')

                            # Salva l'immagine in un buffer temporaneo mantenendo la qualità originale
                            img_buffer = io.BytesIO()
                            # Mantieni il formato originale se possibile, altrimenti usa JPEG a qualità massima
                            if filename.lower().endswith(('.png', '.gif', '.bmp', '.tiff')):
                                img.save(img_buffer, format='PNG')
                            else:
                                img.save(img_buffer, format='JPEG', quality=100)
                            img_buffer.seek(0)

                            # Calcola le dimensioni per adattare l'immagine alla pagina
                            img_width, img_height = img.size

                            # Calcola le dimensioni del logo per riservare spazio
                            logo_space_height = 0
                            if logo_image:
                                logo_width_px = 120
                                logo_width_pt = logo_width_px * 0.75  # Conversione px a punti
                                logo_original_width, logo_original_height = logo_image.size
                                logo_height_pt = (logo_original_height / logo_original_width) * logo_width_pt
                                logo_space_height = logo_height_pt + 1  # Spazio logo + margine minimissimo

                            # Calcola il fattore di scala per adattare l'immagine alla pagina
                            # Lascia margini: 50 punti ai lati, 50 in basso, e spazio per il logo in alto
                            margin = 50
                            margin_top = margin + logo_space_height  # Margine superiore maggiore per il logo
                            max_width = page_width - 2 * margin
                            max_height = page_height - margin - margin_top  # Altezza ridotta per il logo

                            scale_x = max_width / img_width
                            scale_y = max_height / img_height
                            scale = min(scale_x, scale_y)  # Usa il fattore più piccolo per mantenere le proporzioni

                            # Nuove dimensioni scalate
                            scaled_width = img_width * scale
                            scaled_height = img_height * scale

                            # Centra l'immagine nella pagina (sotto il logo)
                            x = (page_width - scaled_width) / 2
                            y = (page_height - margin_top - scaled_height) / 2

                            # Disegna l'immagine nel PDF
                            c.drawImage(ImageReader(img_buffer), x, y, scaled_width, scaled_height)

                            # Aggiungi il logo in alto a sinistra
                            if logo_image:
                                try:
                                    # Salva il logo in un buffer
                                    logo_buffer = io.BytesIO()
                                    logo_image.save(logo_buffer, format='PNG')
                                    logo_buffer.seek(0)

                                    # Calcola le dimensioni del logo (120px di larghezza)
                                    logo_width_px = 120
                                    logo_width_pt = logo_width_px * 0.75  # Conversione px a punti (1px = 0.75pt)

                                    # Calcola l'altezza mantenendo le proporzioni
                                    logo_original_width, logo_original_height = logo_image.size
                                    logo_height_pt = (logo_original_height / logo_original_width) * logo_width_pt

                                    # Posizione in alto a sinistra con margine
                                    logo_x = margin
                                    logo_y = page_height - margin - logo_height_pt

                                    # Disegna il logo
                                    c.drawImage(ImageReader(logo_buffer), logo_x, logo_y, logo_width_pt, logo_height_pt)

                                    print(f"Logo aggiunto alla pagina {i+1} ({logo_width_pt:.0f}x{logo_height_pt:.0f} pt)")
                                except Exception as e:
                                    print(f"Errore nell'aggiunta del logo alla pagina {i+1}: {e}")

                            print(f"Immagine {filename} aggiunta al PDF ({img_width}x{img_height} -> {scaled_width:.0f}x{scaled_height:.0f})")

                    except Exception as e:
                        print(f"ERRORE nell'elaborazione di {filename}: {e}")
                        # Crea una pagina con messaggio di errore
                        c.drawString(100, 400, f"Errore nel caricare l'immagine: {filename}")
                        c.drawString(100, 380, f"Errore: {str(e)}")

                    # Crea una nuova pagina (tranne per l'ultima immagine)
                    if i < len(image_files) - 1:
                        c.showPage()

            # Finalizza il PDF
            c.save()

        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()
        print(f"PDF creato con successo! Dimensione: {len(pdf_bytes)} bytes")
        return pdf_bytes

    except Exception as e:
        print(f"ERRORE nella creazione del PDF: {e}")
        # Crea un PDF di errore
        error_pdf = io.BytesIO()
        c = canvas.Canvas(error_pdf, pagesize=A4)
        c.drawString(100, 750, f"Errore nella creazione del PDF:")
        c.drawString(100, 730, str(e))
        c.save()
        error_pdf.seek(0)
        return error_pdf.getvalue()

def add_screenshot_to_pdf(pdf_bytes: bytes, link: str, logo_image=None) -> bytes:
    """
    Aggiunge una pagina con screenshot del link al PDF esistente.
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from PyPDF2 import PdfReader, PdfWriter
    import tempfile

    try:
        # Cattura screenshot del sito
        screenshot_url = f"https://api.site-shot.com/?url={link}&userkey=MAAIEYKBJA7MPB7IUMXSH3QNVX&no_ads=1&delay_time=6000&no_cookie_popup=1&width=960&height=1300"
        print(f"Catturando screenshot da: {screenshot_url}")

        screenshot_response = requests.get(screenshot_url, timeout=30)
        screenshot_response.raise_for_status()
        screenshot_bytes = screenshot_response.content
        print(f"Screenshot catturato: {len(screenshot_bytes)} bytes")

        # Apri screenshot con PIL
        screenshot_image = Image.open(io.BytesIO(screenshot_bytes))
        if screenshot_image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', screenshot_image.size, (255, 255, 255))
            if screenshot_image.mode == 'P':
                screenshot_image = screenshot_image.convert('RGBA')
            background.paste(screenshot_image, mask=screenshot_image.split()[-1] if screenshot_image.mode in ('RGBA', 'LA') else None)
            screenshot_image = background
        elif screenshot_image.mode != 'RGB':
            screenshot_image = screenshot_image.convert('RGB')

        # Crea una nuova pagina PDF con lo screenshot
        new_page_buffer = io.BytesIO()
        c = canvas.Canvas(new_page_buffer, pagesize=A4)
        page_width, page_height = A4

        # Calcola dimensioni per lo screenshot
        img_width, img_height = screenshot_image.size

        # Calcola spazio per logo e link
        logo_space_height = 0
        link_space_height = 2  # Minimo assoluto per il link in fondo

        if logo_image:
            logo_width_px = 120
            logo_width_pt = logo_width_px * 0.75
            logo_original_width, logo_original_height = logo_image.size
            logo_height_pt = (logo_original_height / logo_original_width) * logo_width_pt
            logo_space_height = logo_height_pt + 15  # Aumentato da 1 a 15 punti dal logo

        # Calcola dimensioni per l'immagine
        margin = 50
        margin_top = margin + logo_space_height
        margin_bottom = margin + link_space_height
        max_width = page_width - 2 * margin
        max_height = page_height - margin_top - margin_bottom

        scale_x = max_width / img_width
        scale_y = max_height / img_height
        scale = min(scale_x, scale_y)

        scaled_width = img_width * scale
        scaled_height = img_height * scale

        # Centra l'immagine nello spazio disponibile tra logo e link
        x = (page_width - scaled_width) / 2
        y = margin_bottom + (max_height - scaled_height) / 2

        print(f"Posizionamento screenshot: x={x:.1f}, y={y:.1f}")
        print(f"Screenshot inizia a y={y + scaled_height:.1f}")
        print(f"Margine effettivo: {(y + scaled_height) - (page_height - margin - logo_height_pt):.1f} punti")

        # Salva screenshot in buffer
        screenshot_buffer = io.BytesIO()
        screenshot_image.save(screenshot_buffer, format='PNG')
        screenshot_buffer.seek(0)

        # Disegna screenshot
        c.drawImage(ImageReader(screenshot_buffer), x, y, scaled_width, scaled_height)

        # Aggiungi logo in alto a sinistra
        if logo_image:
            try:
                logo_buffer = io.BytesIO()
                logo_image.save(logo_buffer, format='PNG')
                logo_buffer.seek(0)

                logo_x = margin
                logo_y = page_height - margin - logo_height_pt

                c.drawImage(ImageReader(logo_buffer), logo_x, logo_y, logo_width_pt, logo_height_pt)
                print("Logo aggiunto alla pagina screenshot")
            except Exception as e:
                print(f"Errore nell'aggiunta del logo: {e}")

        # Aggiungi link in fondo alla pagina
        c.setFont("Helvetica", 10)
        link_width = c.stringWidth(link, "Helvetica", 10)
        link_x = (page_width - link_width) / 2
        link_y = margin / 2
        c.drawString(link_x, link_y, link)
        print(f"Link aggiunto: {link}")

        # Finalizza la nuova pagina
        c.save()
        new_page_buffer.seek(0)

        # Combina il PDF esistente con la nuova pagina
        # Leggi il PDF esistente
        existing_pdf = PdfReader(io.BytesIO(pdf_bytes))
        new_page_pdf = PdfReader(new_page_buffer)

        # Crea il PDF finale
        writer = PdfWriter()

        # Aggiungi tutte le pagine esistenti
        for page in existing_pdf.pages:
            writer.add_page(page)

        # Aggiungi la nuova pagina con lo screenshot
        writer.add_page(new_page_pdf.pages[0])

        # Salva il PDF finale
        final_pdf_buffer = io.BytesIO()
        writer.write(final_pdf_buffer)
        final_pdf_buffer.seek(0)

        final_pdf_bytes = final_pdf_buffer.getvalue()
        print(f"PDF aggiornato con {len(existing_pdf.pages) + 1} pagine, dimensione: {len(final_pdf_bytes)} bytes")

        return final_pdf_bytes

    except Exception as e:
        print(f"ERRORE nell'aggiunta dello screenshot per {link}: {e}")
        # Restituisce il PDF originale in caso di errore
        return pdf_bytes

def add_multiple_screenshots_to_pdf(pdf_bytes: bytes, links: list) -> bytes:
    """
    Aggiunge più pagine con screenshot dei link al PDF esistente.
    """
    # Scarica il logo una sola volta
    logo_bytes = download_logo()
    logo_image = None
    if logo_bytes:
        try:
            logo_image = Image.open(io.BytesIO(logo_bytes))
            if logo_image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', logo_image.size, (255, 255, 255))
                if logo_image.mode == 'P':
                    logo_image = logo_image.convert('RGBA')
                background.paste(logo_image, mask=logo_image.split()[-1] if logo_image.mode in ('RGBA', 'LA') else None)
                logo_image = background
            elif logo_image.mode != 'RGB':
                logo_image = logo_image.convert('RGB')
            print("Logo preparato per tutti gli screenshot")
        except Exception as e:
            print(f"Errore nella preparazione del logo: {e}")
            logo_image = None

    # Elabora ogni link separatamente
    current_pdf_bytes = pdf_bytes
    for i, link in enumerate(links):
        print(f"\n{'='*40}")
        print(f"ELABORANDO LINK {i+1}/{len(links)}")
        print(f"Link: {link}")
        print(f"{'='*40}")
        
        # Processa questo specifico link
        current_pdf_bytes = add_screenshot_to_pdf(current_pdf_bytes, link.strip(), logo_image)
        
        print(f"Link {i+1} completato, PDF size: {len(current_pdf_bytes)} bytes")
    
    print(f"\nTutti i {len(links)} link elaborati!")
    return current_pdf_bytes

@app.post("/aggiungi_screenshot")
async def aggiungi_screenshot(request: Request):
    """
    Endpoint che riceve un PDF nel body e uno o più link nell'header separati da virgola,
    cattura uno screenshot per ogni link e li aggiunge al PDF.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"NUOVA RICHIESTA AGGIUNGI_SCREENSHOT - {timestamp}")
    print("=" * 60)

    try:
        # Leggi il link dall'header
        links_header = request.headers.get("link")
        if not links_header:
            return {
                "status": "error",
                "message": "Header 'link' mancante",
                "timestamp": timestamp
            }

        # Dividi i link per virgola e pulisci spazi
        links = [link.strip() for link in links_header.split(",") if link.strip()]
        
        if not links:
            return {
                "status": "error",
                "message": "Nessun link valido trovato nell'header",
                "timestamp": timestamp
            }

        print(f"Link ricevuti ({len(links)}):")
        for i, link in enumerate(links):
            print(f"  {i+1}. {link}")

        # Leggi il PDF dal body
        pdf_bytes = await request.body()
        if not pdf_bytes:
            return {
                "status": "error", 
                "message": "Body PDF vuoto",
                "timestamp": timestamp
            }

        print(f"PDF ricevuto: {len(pdf_bytes)} bytes")

        # Verifica che sia un PDF valido
        if not pdf_bytes.startswith(b'%PDF'):
            return {
                "status": "error",
                "message": "Il body non contiene un PDF valido",
                "timestamp": timestamp
            }

        print("Inizio elaborazione screenshot...")

        # Aggiungi screenshot per tutti i link al PDF (UNA CHIAMATA API PER OGNI LINK)
        final_pdf_bytes = add_multiple_screenshots_to_pdf(pdf_bytes, links)

        print(f"Tutti gli screenshot aggiunti con successo! PDF finale: {len(final_pdf_bytes)} bytes")

        # Restituisci il PDF modificato
        return StreamingResponse(
            io.BytesIO(final_pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=pdf_with_screenshots_{timestamp.replace(' ', '_').replace(':', '-')}.pdf"
            }
        )

    except Exception as e:
        print(f"ERRORE nell'endpoint aggiungi_screenshot: {e}")
        return {
            "status": "error",
            "message": f"Errore nell'elaborazione: {str(e)}",
            "timestamp": timestamp
        }

@app.post("/genera_pdf")
async def genera_pdf(
    request: Request, 
    file: Optional[UploadFile] = File(None),
    zip_data: Optional[str] = Form(None),  # Per dati ZIP in base64 da n8n
    pdf_data: Optional[PDFRequest] = None
):
    """
    Endpoint POST per generare PDF.
    Riceve file ZIP binari da n8n e stampa tutto quello che arriva.
    """

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"NUOVA RICHIESTA GENERA_PDF - {timestamp}")
    print("=" * 60)

    # Stampa headers
    print("\n--- HEADERS ---")
    for header_name, header_value in request.headers.items():
        print(f"{header_name}: {header_value}")

    # Stampa metodo HTTP
    print(f"\n--- METODO HTTP ---")
    print(f"Metodo: {request.method}")

    # Stampa URL e query parameters
    print(f"\n--- URL INFO ---")
    print(f"URL: {request.url}")
    print(f"Path: {request.url.path}")
    if request.query_params:
        print("Query Parameters:")
        for param, value in request.query_params.items():
            print(f"  {param}: {value}")

    # Stampa client info
    print(f"\n--- CLIENT INFO ---")
    print(f"Client Host: {request.client.host if request.client else 'N/A'}")
    print(f"Client Port: {request.client.port if request.client else 'N/A'}")

    # Gestione FILE ZIP UPLOAD
    zip_binary_data = None
    if file:
        print(f"\n--- FILE UPLOAD ---")
        print(f"Nome file: {file.filename}")
        print(f"Content Type: {file.content_type}")
        print(f"Size: {file.size if hasattr(file, 'size') else 'N/A'}")

        try:
            zip_binary_data = await file.read()
            print(f"Dimensioni file letto: {len(zip_binary_data)} bytes")
            print(f"Primi 50 bytes (hex): {zip_binary_data[:50].hex()}")

            # Verifica se è un file ZIP valido
            try:
                with zipfile.ZipFile(io.BytesIO(zip_binary_data), 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    print(f"File ZIP valido! Contiene {len(file_list)} file:")
                    for zip_file in file_list:
                        file_info = zip_ref.getinfo(zip_file)
                        print(f"  - {zip_file} ({file_info.file_size} bytes)")

                        # Leggi il contenuto di ogni file nel ZIP
                        try:
                            file_content = zip_ref.read(zip_file)
                            print(f"    Contenuto ({len(file_content)} bytes):")
                            # Prova a stampare come testo se possibile
                            try:
                                text_content = file_content.decode('utf-8')[:200]
                                print(f"    Testo: {text_content}...")
                            except:
                                print(f"    Binario (hex): {file_content[:50].hex()}...")
                        except Exception as e:
                            print(f"    Errore lettura file: {e}")

            except zipfile.BadZipFile:
                print("ATTENZIONE: Il file non è un ZIP valido!")
            except Exception as e:
                print(f"Errore nell'analisi ZIP: {e}")

        except Exception as e:
            print(f"Errore nel leggere il file: {e}")

    # Gestione ZIP DATA in base64 (tipico di n8n)
    if zip_data:
        print(f"\n--- ZIP DATA BASE64 ---")
        print(f"Lunghezza stringa base64: {len(zip_data)}")
        print(f"Primi 100 caratteri: {zip_data[:100]}...")

        try:
            # Decodifica da base64
            zip_binary_data = base64.b64decode(zip_data)
            print(f"Dimensioni dopo decodifica base64: {len(zip_binary_data)} bytes")
            print(f"Primi 50 bytes (hex): {zip_binary_data[:50].hex()}")

            # Analizza il contenuto ZIP
            try:
                with zipfile.ZipFile(io.BytesIO(zip_binary_data), 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    print(f"ZIP da base64 valido! Contiene {len(file_list)} file:")
                    for zip_file in file_list:
                        file_info = zip_ref.getinfo(zip_file)
                        print(f"  - {zip_file} ({file_info.file_size} bytes)")

                        # Leggi il contenuto
                        try:
                            file_content = zip_ref.read(zip_file)
                            print(f"    Contenuto ({len(file_content)} bytes):")
                            try:
                                text_content = file_content.decode('utf-8')[:200]
                                print(f"    Testo: {text_content}...")
                            except:
                                print(f"    Binario (hex): {file_content[:50].hex()}...")
                        except Exception as e:
                            print(f"    Errore lettura: {e}")

            except zipfile.BadZipFile:
                print("ATTENZIONE: I dati base64 non sono un ZIP valido!")
        except Exception as e:
            print(f"Errore nella decodifica base64: {e}")

    # Stampa body raw della richiesta E ESTRAI IL ZIP
    try:
        body = await request.body()
        if body and not file and not zip_data:  # Solo se non abbiamo già gestito file/zip_data
            print(f"\n--- RAW BODY ---")
            print(f"Body size: {len(body)} bytes")

            # Se è binario (possibile ZIP), analizza E SALVA
            if body.startswith(b'PK'):  # Magic number per ZIP
                print("Body sembra essere un file ZIP!")
                zip_binary_data = body  # IMPORTANTE: salva il body come zip_binary_data
                try:
                    with zipfile.ZipFile(io.BytesIO(body), 'r') as zip_ref:
                        file_list = zip_ref.namelist()
                        print(f"ZIP nel body contiene {len(file_list)} file:")
                        for zip_file in file_list[:5]:  # Primi 5 file
                            print(f"  - {zip_file}")
                except:
                    print("Errore nell'analisi ZIP dal body")
            else:
                # Prova come testo
                try:
                    body_str = body.decode('utf-8')
                    print(f"Body (primi 500 char): {body_str[:500]}")
                    try:
                        body_json = json.loads(body_str)
                        print(f"Body JSON: {json.dumps(body_json, indent=2, ensure_ascii=False)[:1000]}")
                    except:
                        pass
                except:
                    print(f"Body binario (hex): {body[:100].hex()}")
    except Exception as e:
        print(f"Errore nel leggere il body: {e}")

    # Stampa dati validati da Pydantic
    if pdf_data:
        print(f"\n--- DATI VALIDATI PYDANTIC ---")
        print(f"Titolo: {pdf_data.titolo}")
        print(f"Contenuto: {pdf_data.contenuto}")
        print(f"Parametri: {pdf_data.parametri}")
        print(f"Dati completi: {pdf_data.model_dump()}")

    print("=" * 60)
    print("FINE STAMPA RICHIESTA")
    print("=" * 60)

    # CREAZIONE DEL PDF DALLE IMMAGINI
    if zip_binary_data:
        print("\n" + "=" * 60)
        print("INIZIO CREAZIONE PDF")
        print("=" * 60)

        pdf_bytes = create_pdf_from_images(zip_binary_data)

        print("=" * 60)
        print("FINE CREAZIONE PDF")
        print("=" * 60)

        # Restituisci il PDF come file binario
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=generated_pdf_{timestamp.replace(' ', '_').replace(':', '-')}.pdf"
            }
        )
    else:
        # Nessun file ZIP ricevuto
        return {
            "status": "error",
            "message": "Nessun file ZIP ricevuto",
            "timestamp": timestamp
        }

@app.get("/")
async def root():
    """Endpoint di test per verificare che l'API funzioni"""
    return {"message": "FastAPI PDF Generator è attivo!"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        # reload only useful during local dev; disable in prod
    )
