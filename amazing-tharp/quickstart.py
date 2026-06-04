"""
Quick Start Script
Tests basic functionality of the Literature Search Tool
"""

from pipeline import LiteratureSearchPipeline


def main():
    """Run a quick test of the complete pipeline"""
    
    print("="*60)
    print("Literature Search Tool - Quick Start Test")
    print("="*60)
    print()
    
    # Initialize pipeline
    print("Initializing pipeline...")
    pipeline = LiteratureSearchPipeline(
        db_path="data/test_articles.db",
        embedding_model='general'  # Fast model for testing
    )
    
    # Check current status
    stats = pipeline.get_statistics()
    print(f"\nCurrent database status:")
    print(f"  Articles: {stats['total_articles']}")
    print(f"  Embeddings: {stats['articles_with_embeddings']}")
    print(f"  Clusters: {stats['num_clusters']}")
    
    # Ask user if they want to fetch articles
    if stats['total_articles'] == 0:
        print("\n" + "="*60)
        print("STEP 1: Fetch Articles")
        print("="*60)
        
        fetch = input("\nNo articles in database. Fetch some? (y/n): ").lower()
        
        if fetch == 'y':
            email = input("Enter your email (required by NCBI): ")
            query = input("Enter search query (default: 'machine learning healthcare'): ")
            
            if not query:
                query = "machine learning healthcare"
            
            print(f"\nFetching articles for: '{query}'")
            print("This may take a few minutes...")
            
            pipeline.fetch_articles(
                query=query,
                max_results=100,  # Small number for testing
                email=email
            )
            
            stats = pipeline.get_statistics()
            print(f"\n✓ Fetched {stats['total_articles']} articles")
    
    # Create embeddings if needed
    if stats['total_articles'] > 0 and stats['articles_with_embeddings'] == 0:
        print("\n" + "="*60)
        print("STEP 2: Create Embeddings")
        print("="*60)
        
        create_emb = input("\nCreate embeddings? (y/n): ").lower()
        
        if create_emb == 'y':
            print("\nCreating embeddings...")
            print("This may take a few minutes...")
            
            pipeline.create_embeddings()
            
            stats = pipeline.get_statistics()
            print(f"\n✓ Created embeddings for {stats['articles_with_embeddings']} articles")
    
    # Cluster articles if we have embeddings
    if stats['articles_with_embeddings'] > 0 and stats['num_clusters'] == 0:
        print("\n" + "="*60)
        print("STEP 3: Cluster Articles")
        print("="*60)
        
        cluster = input("\nCluster articles? (y/n): ").lower()
        
        if cluster == 'y':
            n_clusters = input("Number of clusters (default: 5): ")
            n_clusters = int(n_clusters) if n_clusters else 5
            
            print(f"\nClustering into {n_clusters} groups...")
            
            pipeline.cluster_articles(n_clusters=n_clusters, method='kmeans')
            
            stats = pipeline.get_statistics()
            print(f"\n✓ Created {stats['num_clusters']} clusters")
    
    # Create visualizations
    if stats['num_clusters'] > 0:
        print("\n" + "="*60)
        print("STEP 4: Create Visualizations")
        print("="*60)
        
        viz = input("\nCreate visualizations? (y/n): ").lower()
        
        if viz == 'y':
            print("\nCreating visualizations...")
            
            pipeline.create_visualizations(output_dir="data/visualizations")
            
            print("\n✓ Visualizations saved to data/visualizations/")
            print("  - clusters_2d.html (interactive 2D plot)")
            print("  - cluster_summary.html (bar chart)")
            print("  - similarity_heatmap.png (heatmap)")
    
    # Test similarity search
    if stats['articles_with_embeddings'] > 0:
        print("\n" + "="*60)
        print("STEP 5: Test Similarity Search")
        print("="*60)
        
        search = input("\nTest similarity search? (y/n): ").lower()
        
        if search == 'y':
            print("\nExample query:")
            print("'We are studying the use of AI to predict patient outcomes'")
            
            query = input("\nEnter your query (or press Enter for example): ")
            
            if not query:
                query = "We are studying the use of AI to predict patient outcomes from electronic health records"
            
            print(f"\nSearching for similar articles...")
            
            results = pipeline.search_similar(query, top_k=5)
            
            print(f"\n✓ Found {len(results)} similar articles")
    
    # Detect duplicates
    if stats['articles_with_embeddings'] > 10:
        print("\n" + "="*60)
        print("STEP 6: Detect Duplicates")
        print("="*60)
        
        dup = input("\nDetect potential duplicates? (y/n): ").lower()
        
        if dup == 'y':
            print("\nDetecting duplicates (threshold: 0.95)...")
            
            duplicates = pipeline.detect_duplicates(threshold=0.95)
            
            if duplicates:
                print(f"\n✓ Found {len(duplicates)} potential duplicate pairs")
            else:
                print("\n✓ No duplicates found")
    
    # Final summary
    print("\n" + "="*60)
    print("SETUP COMPLETE!")
    print("="*60)
    
    stats = pipeline.get_statistics()
    print(f"\nFinal database status:")
    print(f"  Articles: {stats['total_articles']}")
    print(f"  Embeddings: {stats['articles_with_embeddings']}")
    print(f"  Clusters: {stats['num_clusters']}")
    
    print("\n" + "="*60)
    print("NEXT STEPS")
    print("="*60)
    print("\n1. Launch the web interface:")
    print("   cd app")
    print("   streamlit run streamlit_app.py")
    print("\n2. Open your browser to the URL shown")
    print("\n3. Explore the features:")
    print("   - Search for similar articles")
    print("   - View cluster visualizations")
    print("   - Export results to CSV")
    
    print("\n" + "="*60)
    
    # Close pipeline
    pipeline.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
    except Exception as e:
        print(f"\n\nError: {e}")
        print("Please check the README.md for troubleshooting tips")
