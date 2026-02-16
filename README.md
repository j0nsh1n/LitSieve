# Literature Search & Similarity Tool 📚

A powerful tool for finding similar research papers using semantic search, clustering, and visualization. Built with NLP, embeddings, and machine learning.

## Features

✨ **Core Functionality:**
- 🔍 Fetch research articles from PubMed
- 🧠 Create semantic embeddings using pre-trained models
- 📊 Cluster similar articles automatically
- 🎯 Search for papers similar to your research
- 📈 Interactive visualizations (UMAP, heatmaps, cluster plots)
- 🔄 Duplicate detection
- 💾 SQLite database for efficient storage

🌐 **Web Interface:**
- User-friendly Streamlit interface
- PICO format support for medical research
- Export results to CSV/PDF
- Real-time search and filtering

## Project Structure

```
literature_search_tool/
├── src/
│   ├── pubmed_fetcher.py      # Fetch articles from PubMed
│   ├── database.py             # SQLite database management
│   ├── embeddings.py           # Create and compare embeddings
│   ├── clustering.py           # Clustering and visualization
│   └── pipeline.py             # Main orchestration pipeline
├── app/
│   └── streamlit_app.py        # Web interface
├── data/                       # Data storage (created automatically)
├── notebooks/                  # Jupyter notebooks (optional)
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Setup

1. **Clone or download this project**

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Set up directories:**
```bash
mkdir -p data data/visualizations
```

## Usage

### Option 1: Web Interface (Recommended)

Launch the Streamlit app:

```bash
cd app
streamlit run streamlit_app.py
```

Then navigate to:
1. **Data Management** → Fetch articles from PubMed
2. **Data Management** → Create embeddings
3. **Data Management** → Cluster articles
4. **Search Similar** → Find papers similar to your research
5. **View Clusters** → Explore visualizations

### Option 2: Python API

```python
from src.pipeline import LiteratureSearchPipeline

# Initialize pipeline
pipeline = LiteratureSearchPipeline(
    db_path="data/articles.db",
    embedding_model='general'  # or 'pubmedbert' for better accuracy
)

# Step 1: Fetch articles
pipeline.fetch_articles(
    query="machine learning healthcare",
    max_results=1000,
    email="your.email@example.com"  # Required by NCBI
)

# Step 2: Create embeddings
pipeline.create_embeddings()

# Step 3: Cluster articles
pipeline.cluster_articles(n_clusters=10, method='kmeans')

# Step 4: Create visualizations
pipeline.create_visualizations()

# Search for similar articles
results = pipeline.search_similar(
    query_text="""
    We are studying the use of deep learning to predict
    patient outcomes from electronic health records.
    """,
    top_k=10
)

# Detect duplicates
duplicates = pipeline.detect_duplicates(threshold=0.95)

# Clean up
pipeline.close()
```

### Option 3: Command-Line Script

Create a simple script `run_pipeline.py`:

```python
from src.pipeline import LiteratureSearchPipeline

pipeline = LiteratureSearchPipeline()

# Customize your workflow
pipeline.fetch_articles(
    query="YOUR_SEARCH_QUERY",
    max_results=500,
    email="your.email@example.com"
)

pipeline.create_embeddings()
pipeline.cluster_articles(n_clusters=8)
pipeline.create_visualizations()

pipeline.close()
```

Run it:
```bash
python run_pipeline.py
```

## Embedding Models

The tool supports multiple embedding models:

| Model | Speed | Accuracy | Best For |
|-------|-------|----------|----------|
| `general` | ⚡⚡⚡ Fast | Good | General text, quick testing |
| `pubmedbert` | ⚡⚡ Medium | ⭐⭐⭐ Excellent | Biomedical research |
| `biosentbert` | ⚡⚡ Medium | ⭐⭐⭐ Excellent | Medical text |
| `specter` | ⚡ Slow | ⭐⭐⭐ Excellent | Scientific papers |

**Recommendation:** Start with `general` for testing, then use `pubmedbert` for production.

## Example Queries

### PubMed Search Queries
```
"machine learning healthcare"
"deep learning medical imaging"
"natural language processing clinical notes"
"AI diagnosis cancer"
```

### Similarity Search Queries
```
Study Description:
"We are investigating whether machine learning models can predict
hospital readmission rates using electronic health record data from
diabetic patients."

PICO Format:
Population: Adults with type 2 diabetes
Intervention: Machine learning prediction model
Comparison: Standard risk assessment
Outcome: 30-day hospital readmission
```

## Visualizations

The tool creates three types of visualizations:

1. **2D Cluster Plot** (`clusters_2d.html`)
   - Interactive scatter plot using UMAP dimensionality reduction
   - Hover to see article titles
   - Color-coded by cluster

2. **Cluster Summary** (`cluster_summary.html`)
   - Bar chart showing articles per cluster
   - Cluster labels based on key terms

3. **Similarity Heatmap** (`similarity_heatmap.png`)
   - Pairwise similarity matrix
   - Identifies duplicate or highly similar papers

## Database Schema

The SQLite database contains three tables:

**articles**
- pmid (PRIMARY KEY)
- title, abstract, year, authors, journal

**embeddings**
- pmid (PRIMARY KEY)
- embedding (BLOB - pickled numpy array)
- model_name

**clusters**
- pmid (PRIMARY KEY)
- cluster_id
- cluster_label

## Performance Tips

1. **Start Small:** Test with 100-500 articles first
2. **Batch Processing:** Fetch articles in batches of 200-500
3. **Model Selection:** Use `general` model for quick tests
4. **Clustering:** 5-15 clusters works well for most datasets
5. **Memory:** Large datasets (10,000+ articles) may need 8GB+ RAM

## Troubleshooting

### Common Issues

**"No module named 'Bio'"**
```bash
pip install biopython
```

**"NCBI API Error"**
- Provide a valid email address
- Don't exceed 3 requests per second
- Consider getting an NCBI API key for higher limits

**"Out of Memory"**
- Reduce batch size in fetcher
- Use `general` model instead of biomedical models
- Process in smaller chunks

**"No embeddings found"**
- Make sure you run `create_embeddings()` after fetching articles
- Check database: `pipeline.get_statistics()`

## Advanced Features

### PICO Extraction
```python
from src.embeddings import PICOExtractor

pico = PICOExtractor.extract_pico(abstract_text)
print(pico)  # Dictionary with P, I, C, O elements
```

### Custom Clustering
```python
from src.clustering import ArticleClusterer, ClusterLabeler

clusterer = ArticleClusterer(n_clusters=15, method='hierarchical')
labels = clusterer.fit(embeddings)

# Generate better labels with LLM (requires API)
cluster_labels = ClusterLabeler.generate_llm_labels(articles_by_cluster)
```

### Export Results
```python
import pandas as pd

# Export to CSV
df = pd.DataFrame(results)
df.to_csv('search_results.csv', index=False)

# Export to JSON
import json
with open('results.json', 'w') as f:
    json.dump(results, f, indent=2)
```

## Development Timeline

Based on your project plan:

- ✅ **December**: Project setup, PubMed fetcher, data storage
- ✅ **January**: Embeddings, similarity search, PICO extraction
- ✅ **February**: Clustering, visualizations (current phase!)
- ⏳ **March**: UI polish, testing, documentation

## Next Steps

1. **Test the system:**
   ```bash
   cd app
   streamlit run streamlit_app.py
   ```

2. **Fetch your first dataset:**
   - Use the web interface
   - Start with 100-200 articles
   - Try different search queries

3. **Experiment with models:**
   - Compare `general` vs `pubmedbert`
   - Adjust number of clusters
   - Try different visualization settings

4. **Customize:**
   - Modify cluster labels
   - Add new visualizations
   - Integrate with your workflow

## Resources

- [PubMed API Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [Sentence Transformers](https://www.sbert.net/)
- [UMAP Documentation](https://umap-learn.readthedocs.io/)
- [Streamlit Documentation](https://docs.streamlit.io/)

## License

This project is for educational purposes. Please cite original papers when using in publications.

## Contact

For questions or issues, please open an issue in the repository.

---

**Happy researching! 📚🔬**
