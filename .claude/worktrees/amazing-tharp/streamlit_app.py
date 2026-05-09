"""
Streamlit Web Interface
Interactive UI for the Literature Search Tool
"""

import streamlit as st
import pandas as pd
import os

from pipeline import LiteratureSearchPipeline
from embeddings import EmbeddingEngine, PICOExtractor


# Page configuration
st.set_page_config(
    page_title="Literature Search Tool",
    page_icon="📚",
    layout="wide"
)

# Initialize session state
if 'pipeline' not in st.session_state:
    st.session_state.pipeline = LiteratureSearchPipeline(
        db_path="articles.db",
        embedding_model='general'
    )

if 'search_results' not in st.session_state:
    st.session_state.search_results = None


# Title and description
st.title("📚 Literature Search & Similarity Tool")
st.markdown("""
This tool helps you find similar research studies using semantic search and clustering.
Upload your study description or search query to find relevant papers from PubMed.
""")

# Sidebar for navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Choose a page:",
    ["🔍 Search Similar", "📊 View Clusters", "⚙️ Data Management", "📈 Statistics"]
)

# Get statistics for display
stats = st.session_state.pipeline.get_statistics()
st.sidebar.markdown("---")
st.sidebar.metric("Total Articles", stats['total_articles'])
st.sidebar.metric("With Embeddings", stats['articles_with_embeddings'])
st.sidebar.metric("Clusters", stats['num_clusters'])


# Page: Search Similar Articles
if page == "🔍 Search Similar":
    st.header("Search for Similar Articles")
    
    # Input methods
    input_method = st.radio(
        "Input method:",
        ["Text Input", "PICO Format"]
    )
    
    query_text = ""
    
    if input_method == "Text Input":
        query_text = st.text_area(
            "Enter your study description or research question:",
            height=150,
            placeholder="e.g., We are investigating the use of machine learning to predict patient outcomes from electronic health records..."
        )
    
    else:  # PICO Format
        st.markdown("**PICO (Population, Intervention, Comparison, Outcome)**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            population = st.text_input(
                "Population:",
                placeholder="e.g., Adults with type 2 diabetes"
            )
            intervention = st.text_input(
                "Intervention:",
                placeholder="e.g., Metformin treatment"
            )
        
        with col2:
            comparison = st.text_input(
                "Comparison:",
                placeholder="e.g., Placebo or standard care"
            )
            outcome = st.text_input(
                "Outcome:",
                placeholder="e.g., Glycemic control"
            )
        
        # Combine PICO elements
        pico_parts = []
        if population:
            pico_parts.append(f"Population: {population}")
        if intervention:
            pico_parts.append(f"Intervention: {intervention}")
        if comparison:
            pico_parts.append(f"Comparison: {comparison}")
        if outcome:
            pico_parts.append(f"Outcome: {outcome}")
        
        query_text = ". ".join(pico_parts)
    
    # Search parameters
    col1, col2 = st.columns([3, 1])
    with col1:
        top_k = st.slider("Number of results:", 1, 50, 10)
    with col2:
        st.write("")  # Spacing
    
    # Search button
    if st.button("🔍 Search", type="primary", use_container_width=True):
        if query_text:
            with st.spinner("Searching for similar articles..."):
                results = st.session_state.pipeline.search_similar(query_text, top_k=top_k)
                st.session_state.search_results = results
        else:
            st.warning("Please enter a query or fill in PICO fields")
    
    # Display results
    if st.session_state.search_results:
        st.markdown("---")
        st.subheader(f"Top {len(st.session_state.search_results)} Similar Articles")
        
        for i, article in enumerate(st.session_state.search_results, 1):
            with st.expander(
                f"#{i} [{article['similarity_score']:.3f}] {article['title']}",
                expanded=(i <= 3)
            ):
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.markdown(f"**Journal:** {article['journal']}")
                with col2:
                    st.markdown(f"**Year:** {article['year']}")
                with col3:
                    st.markdown(f"**PMID:** [{article['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/)")
                
                if article['authors']:
                    st.markdown(f"**Authors:** {', '.join(article['authors'][:3])}")
                
                st.markdown("**Abstract:**")
                st.write(article['abstract'])
                
                # Extract PICO
                st.markdown("**Extracted PICO Elements:**")
                pico = PICOExtractor.extract_pico(article['abstract'])
                
                for component, sentences in pico.items():
                    if sentences:
                        st.markdown(f"*{component.title()}:* {sentences[0][:200]}...")
        
        # Export options
        st.markdown("---")
        st.subheader("Export Results")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV export
            df = pd.DataFrame([{
                'Rank': i+1,
                'Similarity': f"{a['similarity_score']:.3f}",
                'Title': a['title'],
                'Year': a['year'],
                'Journal': a['journal'],
                'PMID': a['pmid'],
                'Authors': ', '.join(a['authors'][:3]) if a['authors'] else ''
            } for i, a in enumerate(st.session_state.search_results)])
            
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download CSV",
                csv,
                "similar_articles.csv",
                "text/csv",
                use_container_width=True
            )
        
        with col2:
            # PDF export (simplified - just text)
            text_export = f"Search Results\n{'='*50}\n\n"
            for i, article in enumerate(st.session_state.search_results, 1):
                text_export += f"{i}. [{article['similarity_score']:.3f}] {article['title']}\n"
                text_export += f"   {article['year']} | {article['journal']} | PMID: {article['pmid']}\n\n"
            
            st.download_button(
                "📄 Download Text",
                text_export,
                "similar_articles.txt",
                "text/plain",
                use_container_width=True
            )


# Page: View Clusters
elif page == "📊 View Clusters":
    st.header("Article Clusters")
    
    if stats['num_clusters'] == 0:
        st.info("No clusters found. Please cluster articles first in the Data Management page.")
    else:
        # Load visualizations if they exist
        viz_dir = "visualizations"
        
        if os.path.exists(os.path.join(viz_dir, 'clusters_2d.html')):
            st.subheader("2D Cluster Visualization")
            with open(os.path.join(viz_dir, 'clusters_2d.html'), 'r', encoding='utf-8') as f:
                html_content = f.read()
            st.components.v1.html(html_content, height=750, scrolling=True)

        if os.path.exists(os.path.join(viz_dir, 'cluster_summary.html')):
            st.subheader("Cluster Summary")
            with open(os.path.join(viz_dir, 'cluster_summary.html'), 'r', encoding='utf-8') as f:
                html_content = f.read()
            st.components.v1.html(html_content, height=550, scrolling=True)
        
        if os.path.exists(os.path.join(viz_dir, 'similarity_heatmap.html')):
            st.subheader("Similarity Heatmap")
            with open(os.path.join(viz_dir, 'similarity_heatmap.html'), 'r', encoding='utf-8') as f:
                html_content = f.read()
            st.components.v1.html(html_content, height=750, scrolling=True)


# Page: Data Management
elif page == "⚙️ Data Management":
    st.header("Data Management")
    
    tab1, tab2, tab3 = st.tabs(["📥 Fetch Articles", "🧠 Create Embeddings", "🔷 Cluster Articles"])
    
    # Tab 1: Fetch Articles
    with tab1:
        st.subheader("Fetch Articles from PubMed")
        
        col1, col2 = st.columns(2)
        
        with col1:
            search_query = st.text_input(
                "PubMed Search Query:",
                placeholder="e.g., machine learning healthcare"
            )
            max_results = st.number_input(
                "Maximum Results:",
                min_value=10,
                max_value=5000,
                value=500,
                step=50
            )
        
        with col2:
            email = st.text_input(
                "Your Email (required by NCBI):",
                placeholder="your.email@example.com"
            )
        
        if st.button("Fetch Articles", type="primary"):
            if search_query and email:
                with st.spinner(f"Fetching up to {max_results} articles..."):
                    st.session_state.pipeline.fetch_articles(
                        query=search_query,
                        max_results=max_results,
                        email=email
                    )
                st.success(f"✓ Articles fetched successfully!")
                st.rerun()
            else:
                st.warning("Please enter both search query and email")
    
    # Tab 2: Create Embeddings
    with tab2:
        st.subheader("Create Embeddings")
        
        st.info(f"Currently {stats['articles_with_embeddings']} of {stats['total_articles']} articles have embeddings")
        
        model_choice = st.selectbox(
            "Embedding Model:",
            ["general", "pubmedbert", "biosentbert", "specter"],
            help="'general' is fastest, biomedical models are more accurate for medical text"
        )
        
        if st.button("Create Embeddings", type="primary"):
            if stats['total_articles'] > 0:
                with st.spinner("Creating embeddings... This may take a few minutes..."):
                    st.session_state.pipeline.embedding_engine = EmbeddingEngine(model_choice)
                    st.session_state.pipeline.embedding_model_name = model_choice
                    st.session_state.pipeline.create_embeddings()
                st.success("✓ Embeddings created successfully!")
                st.rerun()
            else:
                st.warning("No articles in database. Fetch articles first.")
    
    # Tab 3: Cluster Articles
    with tab3:
        st.subheader("Cluster Articles")
        
        col1, col2 = st.columns(2)
        
        with col1:
            n_clusters = st.number_input(
                "Number of Clusters:",
                min_value=2,
                max_value=50,
                value=10,
                step=1
            )
        
        with col2:
            cluster_method = st.selectbox(
                "Clustering Method:",
                ["kmeans", "hierarchical"]
            )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Create Clusters", type="primary"):
                if stats['articles_with_embeddings'] > 0:
                    with st.spinner("Clustering articles..."):
                        st.session_state.pipeline.cluster_articles(
                            n_clusters=n_clusters,
                            method=cluster_method
                        )
                    st.success("✓ Clustering complete!")
                    st.rerun()
                else:
                    st.warning("No embeddings found. Create embeddings first.")
        
        with col2:
            if st.button("Create Visualizations"):
                if stats['num_clusters'] > 0:
                    with st.spinner("Creating visualizations..."):
                        st.session_state.pipeline.create_visualizations()
                    st.success("✓ Visualizations created! Check the 'View Clusters' page.")
                    st.rerun()
                else:
                    st.warning("No clusters found. Create clusters first.")


# Page: Statistics
elif page == "📈 Statistics":
    st.header("Database Statistics")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Articles", stats['total_articles'])
    with col2:
        st.metric("Articles with Embeddings", stats['articles_with_embeddings'])
    with col3:
        st.metric("Number of Clusters", stats['num_clusters'])
    
    # Duplicate detection
    st.markdown("---")
    st.subheader("Duplicate Detection")
    
    threshold = st.slider(
        "Similarity Threshold:",
        min_value=0.80,
        max_value=0.99,
        value=0.95,
        step=0.01
    )
    
    if st.button("Detect Duplicates"):
        with st.spinner("Detecting potential duplicates..."):
            duplicates = st.session_state.pipeline.detect_duplicates(threshold=threshold)
        
        if duplicates:
            st.warning(f"Found {len(duplicates)} potential duplicate pairs")
            
            # Show top duplicates
            for pmid1, pmid2, sim in duplicates[:10]:
                article1 = st.session_state.pipeline.db.get_article_by_pmid(pmid1)
                article2 = st.session_state.pipeline.db.get_article_by_pmid(pmid2)
                
                with st.expander(f"[{sim:.3f}] Potential Duplicate"):
                    st.markdown(f"**Article 1:** {article1['title']}")
                    st.markdown(f"*PMID: {pmid1}*")
                    st.markdown(f"**Article 2:** {article2['title']}")
                    st.markdown(f"*PMID: {pmid2}*")
        else:
            st.success("No duplicates found!")


# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
    <p>Literature Search & Similarity Tool | Built with Streamlit</p>
</div>
""", unsafe_allow_html=True)
