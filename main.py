import re
import io
import csv
import json
import asyncio
import os
from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, Response  # Ajoutez 'Response' ici si nécessaire
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from client import RestClient
from auth import authenticate_user


app = FastAPI()

# Charger les variables d'environnement à partir du fichier .env
load_dotenv()

# Initialiser RestClient avec vos identifiants DataForSEO
dataforseo_username = os.getenv('DATAFORSEO_USERNAME')
dataforseo_password = os.getenv('DATAFORSEO_PASSWORD')
dataforseo_client = RestClient(dataforseo_username, dataforseo_password)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Charger les données de locations.json
json_file_path = 'data/locations.json'
try:
    with open(json_file_path, 'r') as locations_file:
        locations_data = json.load(locations_file)
except FileNotFoundError:
    print(f"Le fichier {json_file_path} n'a pas été trouvé.")
except json.JSONDecodeError as e:
    print(f"Erreur lors de la décodification de JSON : {e}")
except Exception as e:
    print(f"Une erreur s'est produite : {e}")

# Utiliser Jinja2Templates pour charger les modèles HTML depuis le dossier templates
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="templates"), name="static")
app.mount("/images", StaticFiles(directory="images"), name="images")

def clean_and_split_keywords(keywords: str):
    """
    Divise une chaîne de mots-clés en une liste, en supprimant les espaces et sauts de ligne inutiles.
    """
    return [keyword.strip() for keyword in re.split(r',|\r\n|\r|\n', keywords) if keyword.strip()]

# Variable globale pour stocker les données des clusters
global_clusters_data = []


@app.get("/")
async def redirect_to_clustering():
    return RedirectResponse(url="/clustering/")

@app.get("/clustering/")
async def read_item(request: Request, username: str = Depends(authenticate_user)):
    return templates.TemplateResponse("clustering.html", {"request": request, "locations": locations_data})

@app.get("/export_csv")
async def export_csv(username: str = Depends(authenticate_user)):
    global global_clusters_data
    print(f"Export des données des clusters: {global_clusters_data}")
    csv_string = create_csv_string(global_clusters_data)
    return Response(content=csv_string, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=clusters.csv"})

@app.post("/search_volume", response_class=HTMLResponse)
async def search_volume(request: Request, keywords: str = Form(...), location_code: int = Form(...), max_crawl_pages: int = Form(...), similarity_threshold: float = Form(50), username: str = Depends(authenticate_user)):
    print(f"Requête reçue - Mots-clés: {keywords}, Location: {location_code}, ...")
    keywords_list = clean_and_split_keywords(keywords)

    keyword_responses = []
    for keyword in keywords_list:
        # Requête pour le volume de recherche
        search_volume_data = [{
            "location_code": location_code,
            "keywords": [keyword]
        }]

        try:
            search_volume_response = dataforseo_client.post("/v3/keywords_data/google_ads/search_volume/live", search_volume_data)
            # Extraire le volume de recherche global
            volume = search_volume_response['tasks'][0]['result'][0]['search_volume']
            print(f"Volume de recherche pour {keyword}: {volume}")
        except Exception as e:
            print(f"Erreur lors de la récupération du volume de recherche pour {keyword}: {e}")
            continue

        # Requête pour vérifier les résultats SERP avec la limite de pages crawlées
        serp_data = [{
            "language_code": "FR",
            "location_code": location_code,
            "keyword": keyword,
            "depth": max_crawl_pages,
            "device": "mobile"  
        }]

        try:
            serp_response = dataforseo_client.post("/v3/serp/google/organic/live/regular", serp_data)
            urls = [item['url'] for item in serp_response['tasks'][0]['result'][0]['items'] if 'url' in item]
            print(f"Réponse SERP pour {keyword}: {urls}")
            keyword_responses.append({'keyword': keyword, 'volume': volume, 'urls': urls})
        except Exception as e:
            print(f"Erreur SERP pour {keyword}: {e}")

        await asyncio.sleep(2.5)
        
    cluster_results = cluster_keywords(keyword_responses, similarity_threshold)
    print("Résultats du clustering:")

    global global_clusters_data
    global_clusters_data = cluster_results

    # Imprimez la structure des résultats de clustering pour le débogage
    print("Résultats du clustering :")
    for cluster in cluster_results:
            print(f"Cluster: {cluster['name']}, Total Volume: {cluster['total_volume']}, Keywords: {[k['keyword'] for k in cluster['keywords']]}")
            for keyword_data in cluster['keywords']:
                print(f"  Mot-clé: {keyword_data['keyword']}, Volume: {keyword_data['volume']}, Similarité: {keyword_data['similarity'] * 100:.2f}%")
                print(f"  Volume total: {cluster['total_volume']}")

    # Passez les résultats de clustering au modèle HTML
    return templates.TemplateResponse("resultat.html", {"request": request, "clusters": cluster_results})

def cluster_keywords(keyword_responses, similarity_threshold):
    clusters = []

    # Boucle pour créer les clusters
    for keyword_data in keyword_responses:
        keyword = keyword_data['keyword']
        urls = keyword_data['urls']
        volume = keyword_data['volume'] if keyword_data['volume'] is not None else 0

        best_cluster = None
        highest_similarity = 0.5  # Valeur de similarité initiale par défaut

        # Trouver le meilleur cluster pour ce mot-clé
        for cluster in clusters:
            common_urls, similarity = calculate_similarity(cluster['urls'], urls)
            if similarity > highest_similarity:
                highest_similarity = similarity
                if similarity >= similarity_threshold / 100:
                    best_cluster = cluster

        # Ajouter le mot-clé au meilleur cluster ou créer un nouveau cluster
        if best_cluster:
            best_cluster['keywords'].append({"keyword": keyword, "volume": volume, "urls": urls, "similarity": highest_similarity})
            best_cluster['total_volume'] += volume
            best_cluster['urls'] = union(best_cluster['urls'], urls)
        else:
            clusters.append({
                'name': keyword,
                'keywords': [{"keyword": keyword, "volume": volume, "similarity": 1.0, "urls": urls}],
                'total_volume': volume,
                'urls': urls
            })

    # Calculer les URLs similaires pour chaque cluster
    for cluster in clusters:
        # Assurez-vous que le cluster contient des mots-clés
        if not cluster['keywords']:
            continue

        # Déterminer le mot-clé principal (exemple : le mot-clé avec le plus grand volume)
        principal_keyword = max(cluster['keywords'], key=lambda x: x.get('volume', 0))

        # Assurez-vous que le mot-clé principal a des URLs
        if 'urls' not in principal_keyword:
            continue

        principal_urls = set(principal_keyword['urls'])

        # Ajouter les URLs similaires à chaque mot-clé dans le cluster
        for keyword in cluster['keywords']:
            if 'urls' in keyword:
                similar_urls = principal_urls & set(keyword['urls'])
                keyword['similar_urls'] = list(similar_urls)
                print(f"URLs similaires pour le mot-clé '{keyword['keyword']}': {keyword['similar_urls']}")


    return clusters

def calculate_similarity(urls1, urls2):
    common_urls = set(urls1) & set(urls2)
    similarity = len(common_urls) / len(set(urls1) | set(urls2)) if urls1 and urls2 else 0
    return common_urls, similarity

def union(list1, list2):
    return list(set(list1) | set(list2))


def calculate_similarity(urls1, urls2):
    common_urls = set(urls1) & set(urls2)
    similarity = len(common_urls) / len(set(urls1) | set(urls2)) if urls1 and urls2 else 0
    return common_urls, similarity

def union(list1, list2):
    return list(set(list1) | set(list2))

def create_csv_string(clusters):
    output = io.StringIO()
    writer = csv.writer(output)

    # Écrire l'en-tête
    writer.writerow(["Cluster", "Volume"])

    # Écrire les données des clusters
    for cluster in clusters:
        writer.writerow([cluster['name'], cluster['total_volume']])

    return output.getvalue()

@app.get("/resultat/detail/{cluster_index}")
async def cluster_detail(request: Request, cluster_index: int, username: str = Depends(authenticate_user)):
    global global_clusters_data
    if cluster_index < len(global_clusters_data):
        cluster = global_clusters_data[cluster_index]
        print(f"Données du cluster {cluster_index}: {cluster}")  # Débogage
        return templates.TemplateResponse("cluster_detail.html", {"request": request, "cluster": cluster})
    else:
        return RedirectResponse(url="/clustering/")