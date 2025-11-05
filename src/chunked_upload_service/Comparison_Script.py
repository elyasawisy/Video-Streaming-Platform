"""
Upload Methods Comparison Script
Compares HTTP/2 streaming vs Chunked upload performance
"""

import requests
import time
import os
import json
import statistics
from datetime import datetime
import matplotlib.pyplot as plt

HTTP2_API = "http://localhost:8001"
CHUNKED_API = "http://localhost:8002"

class UploadComparison:
    """Compare HTTP/2 vs Chunked upload performance"""
    
    def __init__(self):
        self.results = {
            'http2': [],
            'chunked': []
        }
    
    def create_test_video(self, size_mb, name):
        """Create test video file"""
        filename = f"test_{size_mb}mb_{name}.mp4"
        if not os.path.exists(filename):
            print(f"Creating {size_mb}MB test file...")
            with open(filename, 'wb') as f:
                for _ in range(size_mb):
                    f.write(os.urandom(1024 * 1024))
        return filename
    
    def test_http2_upload(self, filename, title):
        """Test HTTP/2 streaming upload"""
        print(f"\nTesting HTTP/2 Upload: {filename}")
        
        start_time = time.time()
        file_size = os.path.getsize(filename)
        
        try:
            with open(filename, 'rb') as f:
                files = {'video': (filename, f, 'video/mp4')}
                data = {
                    'title': title,
                    'uploader_id': 'comparison-test'
                }
                
                response = requests.post(
                    f"{HTTP2_API}/api/v1/upload",
                    files=files,
                    data=data,
                    timeout=300
                )
                
                duration = time.time() - start_time
                
                if response.status_code == 201:
                    result = response.json()
                    throughput = file_size / duration
                    
                    print(f"HTTP/2 Upload successful")
                    print(f"   Duration: {duration:.2f}s")
                    print(f"   Throughput: {throughput / 1024 / 1024:.2f} MB/s")
                    
                    return {
                        'success': True,
                        'duration': duration,
                        'throughput': throughput,
                        'file_size': file_size,
                        'video_id': result['data']['id']
                    }
                else:
                    print(f"Upload failed: {response.status_code}")
                    return {'success': False}
                    
        except Exception as e:
            duration = time.time() - start_time
            print(f"HTTP/2 error: {e}")
            return {
                'success': False,
                'duration': duration,
                'error': str(e)
            }
    
    def test_chunked_upload(self, filename, title, chunk_size_mb=1):
        """Test chunked upload with resume capability"""
        print(f"\nTesting Chunked Upload: {filename}")
        
        start_time = time.time()
        file_size = os.path.getsize(filename)
        chunk_size = chunk_size_mb * 1024 * 1024
        total_chunks = (file_size + chunk_size - 1) // chunk_size
        
        try:
            # Initialize
            init_data = {
                'filename': os.path.basename(filename),
                'file_size': file_size,
                'total_chunks': total_chunks,
                'title': title
            }
            
            response = requests.post(
                f"{CHUNKED_API}/api/v1/upload/init",
                json=init_data
            )
            
            if response.status_code != 201:
                print(f"Initialization failed: {response.status_code}")
                return {'success': False}
            
            upload_id = response.json()['data']['upload_id']
            video_id = response.json()['data']['video_id']
            
            # Upload chunks
            with open(filename, 'rb') as f:
                for chunk_num in range(1, total_chunks + 1):
                    chunk_data = f.read(chunk_size)
                    
                    files = {'chunk': (f'chunk_{chunk_num}', chunk_data)}
                    data = {
                        'upload_id': upload_id,
                        'chunk_number': str(chunk_num)
                    }
                    
                    response = requests.post(
                        f"{CHUNKED_API}/api/v1/upload/chunk",
                        files=files,
                        data=data
                    )
                    
                    if response.status_code != 200:
                        print(f"Chunk {chunk_num} failed")
                        return {'success': False}
            
            # Complete upload
            complete_data = {'upload_id': upload_id, 'title': title}
            response = requests.post(
                f"{CHUNKED_API}/api/v1/upload/complete",
                json=complete_data
            )
            
            duration = time.time() - start_time
            
            if response.status_code == 200:
                throughput = file_size / duration
                
                print(f"Chunked Upload successful")
                print(f"   Duration: {duration:.2f}s")
                print(f"   Throughput: {throughput / 1024 / 1024:.2f} MB/s")
                print(f"   Chunks: {total_chunks}")
                
                return {
                    'success': True,
                    'duration': duration,
                    'throughput': throughput,
                    'file_size': file_size,
                    'total_chunks': total_chunks,
                    'video_id': video_id
                }
            else:
                print(f"Completion failed: {response.status_code}")
                return {'success': False}
                
        except Exception as e:
            duration = time.time() - start_time
            print(f"Chunked upload error: {e}")
            return {
                'success': False,
                'duration': duration,
                'error': str(e)
            }
    
    def run_comparison(self, file_sizes_mb=[10, 50, 100], iterations=3):
        """Run comparison tests"""
        print("=" * 70)
        print("Upload Methods Comparison")
        print("=" * 70)
        
        for size_mb in file_sizes_mb:
            print(f"\n{'='*70}")
            print(f"Testing {size_mb}MB file ({iterations} iterations)")
            print(f"{'='*70}")
            
            # Create test file
            test_file = self.create_test_video(size_mb, f"comparison_{size_mb}mb")
            
            # Test both methods multiple times
            for i in range(iterations):
                print(f"\n--- Iteration {i+1}/{iterations} ---")
                
                # HTTP/2 test
                result_http2 = self.test_http2_upload(
                    test_file, 
                    f"HTTP/2 Test {size_mb}MB - Iteration {i+1}"
                )
                if result_http2['success']:
                    self.results['http2'].append(result_http2)
                
                time.sleep(2)  # Cool down
                
                # Chunked test
                result_chunked = self.test_chunked_upload(
                    test_file,
                    f"Chunked Test {size_mb}MB - Iteration {i+1}"
                )
                if result_chunked['success']:
                    self.results['chunked'].append(result_chunked)
                
                time.sleep(2)  # Cool down
            
            # Cleanup test file
            if os.path.exists(test_file):
                os.remove(test_file)
    
    def calculate_statistics(self):
        """Calculate performance statistics"""
        stats = {}
        
        for method in ['http2', 'chunked']:
            results = self.results[method]
            
            if not results:
                continue
            
            durations = [r['duration'] for r in results]
            throughputs = [r['throughput'] for r in results]
            
            stats[method] = {
                'count': len(results),
                'duration': {
                    'min': min(durations),
                    'max': max(durations),
                    'avg': statistics.mean(durations),
                    'median': statistics.median(durations),
                    'stdev': statistics.stdev(durations) if len(durations) > 1 else 0
                },
                'throughput': {
                    'min': min(throughputs) / 1024 / 1024,  # MB/s
                    'max': max(throughputs) / 1024 / 1024,
                    'avg': statistics.mean(throughputs) / 1024 / 1024,
                    'median': statistics.median(throughputs) / 1024 / 1024,
                    'stdev': statistics.stdev(throughputs) / 1024 / 1024 if len(throughputs) > 1 else 0
                }
            }
        
        return stats
    
    def print_comparison_table(self, stats):
        """Print comparison results in table format"""
        print("\n" + "=" * 70)
        print("PERFORMANCE COMPARISON RESULTS")
        print("=" * 70)
        
        print("\nUpload Duration (seconds)")
        print(f"{'Metric':<15} {'HTTP/2':<20} {'Chunked':<20} {'Winner':<15}")
        print("-" * 70)
        
        metrics = ['avg', 'median', 'min', 'max', 'stdev']
        for metric in metrics:
            http2_val = stats['http2']['duration'].get(metric, 0)
            chunked_val = stats['chunked']['duration'].get(metric, 0)
            
            if metric != 'stdev':
                winner = 'HTTP/2' if http2_val < chunked_val else 'Chunked'
            else:
                winner = 'HTTP/2' if http2_val < chunked_val else 'Chunked'
            
            print(f"{metric.capitalize():<15} {http2_val:<20.2f} {chunked_val:<20.2f} {winner:<15}")
        
        print("\nThroughput (MB/s)")
        print(f"{'Metric':<15} {'HTTP/2':<20} {'Chunked':<20} {'Winner':<15}")
        print("-" * 70)
        
        for metric in metrics:
            http2_val = stats['http2']['throughput'].get(metric, 0)
            chunked_val = stats['chunked']['throughput'].get(metric, 0)
            
            if metric != 'stdev':
                winner = 'HTTP/2' if http2_val > chunked_val else 'Chunked'
            else:
                winner = 'HTTP/2' if http2_val < chunked_val else 'Chunked'
            
            print(f"{metric.capitalize():<15} {http2_val:<20.2f} {chunked_val:<20.2f} {winner:<15}")
        
        print("\n" + "=" * 70)
        print("KEY FINDINGS:")
        print("=" * 70)
        
        # Determine overall winner
        http2_faster = stats['http2']['duration']['avg'] < stats['chunked']['duration']['avg']
        http2_throughput = stats['http2']['throughput']['avg']
        chunked_throughput = stats['chunked']['throughput']['avg']
        
        print(f"\nSpeed Winner: {'HTTP/2' if http2_faster else 'Chunked'}")
        print(f"   HTTP/2 avg: {stats['http2']['duration']['avg']:.2f}s")
        print(f"   Chunked avg: {stats['chunked']['duration']['avg']:.2f}s")
        
        print(f"\nThroughput Winner: {'HTTP/2' if http2_throughput > chunked_throughput else 'Chunked'}")
        print(f"   HTTP/2 avg: {http2_throughput:.2f} MB/s")
        print(f"   Chunked avg: {chunked_throughput:.2f} MB/s")
        
        print("\n💡 Trade-offs:")
        print("   HTTP/2:")
        print("     + Simpler implementation")
        print("     + Lower overhead")
        print("     - No resume capability")
        print("     - Fails completely on network interruption")
        
        print("\n   Chunked:")
        print("     + Resume capability")
        print("     + Better for unreliable networks")
        print("     + Fine-grained progress tracking")
        print("     - More complex implementation")
        print("     - Higher overhead (multiple requests)")
    
    def save_results(self, filename='comparison_results.json'):
        """Save results to JSON file"""
        timestamp = datetime.now().isoformat()
        output = {
            'timestamp': timestamp,
            'results': self.results,
            'statistics': self.calculate_statistics()
        }
        
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults saved to {filename}")
    
    def plot_results(self):
        """Generate comparison charts"""
        try:
            stats = self.calculate_statistics()
            
            # Create figure with subplots
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
            
            # Duration comparison
            methods = ['HTTP/2', 'Chunked']
            durations = [
                stats['http2']['duration']['avg'],
                stats['chunked']['duration']['avg']
            ]
            
            ax1.bar(methods, durations, color=['#3498db', '#e74c3c'])
            ax1.set_ylabel('Average Duration (seconds)')
            ax1.set_title('Upload Duration Comparison')
            ax1.grid(axis='y', alpha=0.3)
            
            # Add value labels on bars
            for i, v in enumerate(durations):
                ax1.text(i, v, f'{v:.2f}s', ha='center', va='bottom')
            
            # Throughput comparison
            throughputs = [
                stats['http2']['throughput']['avg'],
                stats['chunked']['throughput']['avg']
            ]
            
            ax2.bar(methods, throughputs, color=['#3498db', '#e74c3c'])
            ax2.set_ylabel('Average Throughput (MB/s)')
            ax2.set_title('Throughput Comparison')
            ax2.grid(axis='y', alpha=0.3)
            
            # Add value labels on bars
            for i, v in enumerate(throughputs):
                ax2.text(i, v, f'{v:.2f} MB/s', ha='center', va='bottom')
            
            plt.tight_layout()
            plt.savefig('benchmarks/upload_comparison.png', dpi=300, bbox_inches='tight')
            print("\nChart saved to benchmarks/upload_comparison.png")
            
        except Exception as e:
            print(f"Could not generate chart: {e}")
            print("   Install matplotlib: pip install matplotlib")


def main():
    """Main comparison test"""
    comparison = UploadComparison()
    
    # Run comparison tests
    # Test with 10MB, 50MB, and 100MB files, 3 iterations each
    comparison.run_comparison(
        file_sizes_mb=[10, 50, 100],
        iterations=3
    )
    
    # Calculate and print statistics
    stats = comparison.calculate_statistics()
    comparison.print_comparison_table(stats)
    
    # Save results
    os.makedirs('results', exist_ok=True)
    comparison.save_results('results/upload_comparison.json')
    
    # Generate plots
    os.makedirs('benchmarks', exist_ok=True)
    comparison.plot_results()
    
    print("\n" + "=" * 70)
    print("Comparison complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()