import os
import csv
import io
import requests
from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

# --- Database Config ---
# Set your PostgreSQL connection string in the environment variable DATABASE_URL
# e.g. postgresql://user:password@localhost:5432/bookshelf
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/bookshelf'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# --- Model ---
class Book(db.Model):
    __tablename__ = 'books'
    id           = db.Column(db.Integer, primary_key=True)
    isbn         = db.Column(db.String(20), unique=True, nullable=True)
    title        = db.Column(db.String(512), nullable=False)
    author       = db.Column(db.String(512))
    description  = db.Column(db.Text)
    publisher    = db.Column(db.String(256))
    publish_date = db.Column(db.String(64))
    cover_url    = db.Column(db.String(1024))
    added_at     = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':           self.id,
            'isbn':         self.isbn,
            'title':        self.title,
            'author':       self.author,
            'description':  self.description,
            'publisher':    self.publisher,
            'publish_date': self.publish_date,
            'cover_url':    self.cover_url,
            'added_at':     self.added_at.isoformat() if self.added_at else None,
        }


# --- Open Library Helpers ---
def fetch_by_isbn(isbn):
    isbn = isbn.replace('-', '').replace(' ', '')
    url = f'https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data'
    resp = requests.get(url, timeout=10)
    data = resp.json()
    key = f'ISBN:{isbn}'
    if key not in data:
        return None
    book = data[key]
    cover = None
    if 'cover' in book:
        cover = book['cover'].get('large') or book['cover'].get('medium') or book['cover'].get('small')
    authors = ', '.join(a['name'] for a in book.get('authors', []))
    publishers = ', '.join(p['name'] for p in book.get('publishers', []))
    publish_date = book.get('publish_date', '')
    description = ''
    if 'excerpts' in book and book['excerpts']:
        description = book['excerpts'][0].get('text', '')
    return {
        'isbn':         isbn,
        'title':        book.get('title', ''),
        'author':       authors,
        'description':  description,
        'publisher':    publishers,
        'publish_date': publish_date,
        'cover_url':    cover,
    }


def fetch_by_title(title):
    url = f'https://openlibrary.org/search.json?title={requests.utils.quote(title)}&limit=5'
    resp = requests.get(url, timeout=10)
    data = resp.json()
    results = []
    for doc in data.get('docs', []):
        cover_id = doc.get('cover_i')
        cover_url = f'https://covers.openlibrary.org/b/id/{cover_id}-L.jpg' if cover_id else None
        results.append({
            'isbn':         (doc.get('isbn') or [None])[0],
            'title':        doc.get('title', ''),
            'author':       ', '.join(doc.get('author_name', [])),
            'description':  '',
            'publisher':    ', '.join(doc.get('publisher', [])[:2]),
            'publish_date': str(doc.get('first_publish_year', '')),
            'cover_url':    cover_url,
        })
    return results


# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/lookup/isbn', methods=['GET'])
def lookup_isbn():
    isbn = request.args.get('isbn', '').strip()
    if not isbn:
        return jsonify({'error': 'ISBN required'}), 400
    result = fetch_by_isbn(isbn)
    if not result:
        return jsonify({'error': 'Book not found'}), 404
    return jsonify(result)


@app.route('/api/lookup/title', methods=['GET'])
def lookup_title():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Title required'}), 400
    results = fetch_by_title(title)
    if not results:
        return jsonify({'error': 'No books found'}), 404
    return jsonify(results)


@app.route('/api/books', methods=['GET'])
def list_books():
    q = request.args.get('q', '').strip()
    query = Book.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(Book.title.ilike(like), Book.author.ilike(like), Book.isbn.ilike(like))
        )
    books = query.order_by(Book.added_at.desc()).all()
    return jsonify([b.to_dict() for b in books])


@app.route('/api/books', methods=['POST'])
def add_book():
    data = request.json
    if not data or not data.get('title'):
        return jsonify({'error': 'Title is required'}), 400

    # Check for duplicate ISBN
    if data.get('isbn'):
        existing = Book.query.filter_by(isbn=data['isbn']).first()
        if existing:
            return jsonify({'error': 'A book with this ISBN already exists', 'existing': existing.to_dict()}), 409

    book = Book(
        isbn=data.get('isbn'),
        title=data.get('title'),
        author=data.get('author'),
        description=data.get('description'),
        publisher=data.get('publisher'),
        publish_date=data.get('publish_date'),
        cover_url=data.get('cover_url'),
    )
    db.session.add(book)
    db.session.commit()
    return jsonify(book.to_dict()), 201


@app.route('/api/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    return jsonify({'deleted': True})


@app.route('/api/books/export', methods=['GET'])
def export_csv():
    books = Book.query.order_by(Book.added_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'ISBN', 'Title', 'Author', 'Publisher', 'Publish Date', 'Description', 'Added At'])
    for b in books:
        writer.writerow([b.id, b.isbn, b.title, b.author, b.publisher, b.publish_date, b.description, b.added_at])
    output.seek(0)
    return send_file(
        io.BytesIO(output.read().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='bookshelf.csv'
    )


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
